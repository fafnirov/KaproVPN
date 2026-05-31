"""KaproTUN installer — custom branded setup UI.

Ships as KaproTUN-Setup.exe alongside the portable KaproTUN.exe in each
GitHub release. The portable exe is embedded inside this installer as a
PyInstaller data file; on install it gets copied out to
%LOCALAPPDATA%\\Programs\\KaproTUN\\ and Start Menu + Desktop shortcuts
are created.
"""
