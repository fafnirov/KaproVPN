package pro.kaprovpn.android.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import android.util.Log
import android.view.ViewGroup
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import pro.kaprovpn.android.R
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Сканер QR-кодов с share-URL (vless/vmess/trojan/ss). При первом успешном
 * распознавании дёргает [onScanned] с raw-строкой и сразу останавливает
 * камеру, чтобы не повторяться.
 *
 * Архитектура:
 *  - CameraX `Preview` use-case → [PreviewView] через AndroidView interop.
 *  - CameraX `ImageAnalysis` use-case → ML Kit `BarcodeScanner` на одном
 *    background-executor'е. STRATEGY_KEEP_ONLY_LATEST: если scanner не
 *    успевает — фреймы дропаются, latency камеры остаётся низкой.
 *  - Lifecycle bind через `LocalLifecycleOwner` + `ProcessCameraProvider`.
 *    `DisposableEffect` отвязывает + закрывает scanner + executor на dispose.
 *  - Permission: `rememberLauncherForActivityResult(RequestPermission)`.
 *    На denied показываем rationale + кнопку «Открыть настройки».
 *
 * One-shot guard через [AtomicBoolean] — даже на reentrant фрейме после
 * успешного scan мы не вызовем [onScanned] второй раз.
 *
 * Соответствие десктоп-клиенту: на desktop QR-сканера нет (PySide6 + qrcode
 * только генерируется). Эта фича — мобильно-эксклюзивная.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScanQrScreen(
    modifier: Modifier = Modifier,
    onScanned: (rawValue: String) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    var permissionGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.CAMERA,
            ) == PackageManager.PERMISSION_GRANTED
        )
    }
    var permissionRequested by remember { mutableStateOf(false) }

    val launcher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        permissionGranted = granted
        permissionRequested = true
    }

    LaunchedEffect(Unit) {
        if (!permissionGranted) launcher.launch(Manifest.permission.CAMERA)
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Text(
                        stringResource(R.string.scan_qr_title),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.back),
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when {
                permissionGranted -> CameraPreview(onScanned = onScanned)
                permissionRequested -> CameraDenied(
                    onOpenSettings = {
                        runCatching {
                            val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                                .setData(Uri.fromParts("package", context.packageName, null))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            context.startActivity(intent)
                        }
                    },
                    onBack = onBack,
                )
                else -> {
                    // Permission диалог уже всплыл (LaunchedEffect выше).
                    // Пустое состояние — пользователь видит чёрный фон с
                    // системным prompt поверх. Когда выберет — state обновится.
                }
            }
        }
    }
}

@Composable
private fun CameraPreview(onScanned: (String) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    // One-shot guard: после первого распознанного barcode не вызываем onScanned
    // повторно даже если analyzer уже отдал следующий фрейм с тем же QR.
    val consumed = remember { AtomicBoolean(false) }

    // Один executor на весь lifetime экрана. Закрывается в DisposableEffect.
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }

    val scanner = remember {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                val previewView = PreviewView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    scaleType = PreviewView.ScaleType.FILL_CENTER
                }
                bindCamera(
                    context = ctx,
                    lifecycleOwner = lifecycleOwner,
                    previewView = previewView,
                    cameraExecutor = cameraExecutor,
                    scanner = scanner,
                    consumed = consumed,
                    onScanned = onScanned,
                )
                previewView
            },
        )

        // Прицельная рамка по центру. Чисто визуальный guide — ML Kit
        // обрабатывает весь кадр, не только эту область.
        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .size(260.dp)
                .border(
                    width = 2.dp,
                    color = MaterialTheme.colorScheme.primary,
                    shape = RoundedCornerShape(16.dp),
                ),
        )

        Text(
            text = stringResource(R.string.scan_qr_hint),
            style = MaterialTheme.typography.bodyMedium,
            color = Color.White,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .background(Color.Black.copy(alpha = 0.6f))
                .padding(horizontal = 24.dp, vertical = 16.dp),
        )
    }

    DisposableEffect(Unit) {
        onDispose {
            runCatching { ProcessCameraProvider.getInstance(context).get().unbindAll() }
            runCatching { scanner.close() }
            cameraExecutor.shutdown()
        }
    }
}

@Composable
private fun CameraDenied(
    onOpenSettings: () -> Unit,
    onBack: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(R.string.camera_perm_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.size(8.dp))
        Text(
            text = stringResource(R.string.camera_perm_body),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.size(16.dp))
        Button(onClick = onOpenSettings) {
            Text(stringResource(R.string.camera_perm_open_settings))
        }
        Spacer(Modifier.size(8.dp))
        Button(onClick = onBack) {
            Text(stringResource(R.string.back))
        }
    }
}

/**
 * Поднимает Preview + ImageAnalysis use-cases на CAMERA_BACK + ML Kit scanner.
 * Если уже какой-то bind висит — `unbindAll` чтобы переподнять чисто.
 */
private fun bindCamera(
    context: android.content.Context,
    lifecycleOwner: LifecycleOwner,
    previewView: PreviewView,
    cameraExecutor: java.util.concurrent.ExecutorService,
    scanner: com.google.mlkit.vision.barcode.BarcodeScanner,
    consumed: AtomicBoolean,
    onScanned: (String) -> Unit,
) {
    val providerFuture = ProcessCameraProvider.getInstance(context)
    providerFuture.addListener({
        val provider = providerFuture.get()

        val preview = Preview.Builder().build().apply {
            setSurfaceProvider(previewView.surfaceProvider)
        }

        val analysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()

        analysis.setAnalyzer(cameraExecutor) { imageProxy ->
            if (consumed.get()) {
                imageProxy.close()
                return@setAnalyzer
            }
            val mediaImage = imageProxy.image
            if (mediaImage == null) {
                imageProxy.close()
                return@setAnalyzer
            }
            val input = InputImage.fromMediaImage(
                mediaImage,
                imageProxy.imageInfo.rotationDegrees,
            )
            scanner.process(input)
                .addOnSuccessListener { barcodes ->
                    val raw = barcodes
                        .asSequence()
                        .mapNotNull { it.rawValue }
                        .firstOrNull { looksLikeShareUrl(it) }
                    if (raw != null && consumed.compareAndSet(false, true)) {
                        Log.i(TAG, "QR scanned: ${raw.take(40)}…")
                        onScanned(raw)
                    }
                }
                .addOnFailureListener { e ->
                    Log.w(TAG, "ML Kit barcode scan failed", e)
                }
                .addOnCompleteListener { imageProxy.close() }
        }

        try {
            provider.unbindAll()
            provider.bindToLifecycle(
                lifecycleOwner,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                analysis,
            )
        } catch (e: Throwable) {
            Log.e(TAG, "bindToLifecycle failed", e)
        }
    }, ContextCompat.getMainExecutor(context))
}

/**
 * Грубая отсечка — игнорируем случайно отсканированные http-сайты, wifi-QR,
 * vCard и прочее. Парсинг и валидация делается дальше в [ShareUrlParser]
 * через AddConfigDialog — там пользователь увидит понятный error если URL
 * битый.
 */
private fun looksLikeShareUrl(raw: String): Boolean {
    val lower = raw.trim().lowercase()
    return lower.startsWith("vless://") ||
        lower.startsWith("vmess://") ||
        lower.startsWith("trojan://") ||
        lower.startsWith("ss://") ||
        lower.startsWith("hysteria2://") ||
        lower.startsWith("hy2://")
}

private const val TAG = "ScanQrScreen"
