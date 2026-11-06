@echo off
cd /d "%~dp0"
if not exist "bin\Release\net8.0-windows\FishBotToolPanel.dll" (
    dotnet build "FishBotToolPanel.csproj" -c Release
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
start "" dotnet "bin\Release\net8.0-windows\FishBotToolPanel.dll"
