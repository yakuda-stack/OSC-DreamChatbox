; ---------------------------------------------------------------------
;  OSC-DreamChatbox - Inno Setup script
;
;  Turns the PyInstaller one-folder build into a normal Windows
;  installer with Start-menu entry, uninstaller and (optionally) the
;  Visual C++ redistributable.
;
;  Build order:
;      1) .\packaging\windows\build-exe.ps1 -NoConsole
;      2) open this file in Inno Setup and press Build
;         (or:  iscc packaging\windows\installer.iss )
;
;  Get Inno Setup from https://jrsoftware.org/isdl.php
;
;  WHY AN INSTALLER AND NOT A SINGLE .EXE:
;  see packaging/windows/README-BUILD.md - short version: one-file
;  unpacks ~200 MB into %TEMP% on every single launch, which is slow and
;  a magnet for antivirus false positives. One folder + installer starts
;  instantly and is what users expect on Windows.
; ---------------------------------------------------------------------

#define AppName        "OSC-DreamChatbox"
#define AppPublisher   "yakuda"
#define AppURL         "https://github.com/yakuda-stack/OSC-DreamChatbox"
#define AppExe         "OSC-DreamChatbox.exe"
; Normally passed in by make-release.ps1:  iscc /DAppVersion=1.4.1 installer.iss
; The fallback below only applies when you build the .iss by hand, so it can
; still drift from core/constants.py -> VERSION. Prefer make-release.ps1.
#ifndef AppVersion
  #define AppVersion   "1.4.0"
#endif
; where build-exe.ps1 leaves the one-folder build
#define SourceDir      "..\..\dist\OSC-DreamChatbox"

[Setup]
AppId={{7B3D2A14-9C4E-4F62-B0A7-0C1E5D8F3A21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
; per-user install: no UAC prompt, and the app never needs admin itself
; (the temperature helper asks for elevation on its own, when clicked)
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=OSC-DreamChatbox-{#AppVersion}-setup
SetupIconFile=..\..\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german";  MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart";   Description: "Start with Windows"; \
    GroupDescription: "Startup"; Flags: unchecked

[Files]
; the whole PyInstaller folder, including _internal
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";     Filename: "{app}\{#AppExe}"; \
    Tasks: desktopicon
Name: "{userstartup}\{#AppName}";     Filename: "{app}\{#AppExe}"; \
    Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller writes nothing outside {app}, but a crashed run can leave
; a stale folder behind
Type: filesandordirs; Name: "{app}\_internal"

; NOTE: %APPDATA%\OSC-DreamChatbox is deliberately NOT deleted. That is
; the user's config, plugins, themes and lyrics - uninstalling the app
; should not throw them away. A reinstall picks them straight back up.
