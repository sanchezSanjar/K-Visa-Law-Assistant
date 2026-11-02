@echo off
rem Builds KVisaLaw.exe with the C# compiler included in Windows (.NET Framework 4).
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo C# compiler not found.
  exit /b 1
)
if not exist "..\assets\kvisa.ico" powershell -NoProfile -ExecutionPolicy Bypass -File make_icon.ps1
"%CSC%" /nologo /target:winexe /optimize+ /win32icon:..\assets\kvisa.ico ^
  /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /out:..\KVisaLaw.exe KVisaLaw.cs || exit /b 1
echo Built KVisaLaw.exe
