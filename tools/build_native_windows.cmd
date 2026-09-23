@echo off
setlocal

set "ROOT=%~dp0.."
if not defined PYTHON set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

for /f "delims=" %%I in ('call "%PYTHON%" -c "import sysconfig; print(sysconfig.get_paths()['include'])"') do set "PYTHON_INCLUDE=%%I"
for /f "delims=" %%I in ('call "%PYTHON%" -c "import sysconfig; print(sysconfig.get_config_var('installed_base'))"') do set "PYTHON_BASE=%%I"
for /f "delims=" %%I in ('call "%PYTHON%" -c "import pybind11; print(pybind11.get_include())"') do set "PYBIND_INCLUDE=%%I"
for /f "delims=" %%I in ('call "%PYTHON%" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"') do set "EXT_SUFFIX=%%I"

set "VSDEVCMD=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
if not exist "%VSDEVCMD%" (
    echo Visual Studio 2022 Community C++ tools were not found.
    exit /b 1
)

call "%VSDEVCMD%" -arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%

cl.exe /nologo /std:c++20 /utf-8 /O2 /EHsc /LD ^
    /I"%PYTHON_INCLUDE%" /I"%PYBIND_INCLUDE%" /I"%ROOT%\cpp" ^
    "%ROOT%\cpp\dragons\game.cpp" "%ROOT%\cpp\bindings.cpp" ^
    /link /LIBPATH:"%PYTHON_BASE%\libs" /OUT:"%ROOT%\cpp\_dragons%EXT_SUFFIX%"
if errorlevel 1 exit /b %errorlevel%

echo built %ROOT%\cpp\_dragons%EXT_SUFFIX%
