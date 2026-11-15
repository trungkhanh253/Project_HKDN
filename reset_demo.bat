@echo off
chcp 65001 >nul
echo ========================================================
echo   HE THONG DIEM DANH HKDN - RESET DU LIEU DEMO
echo ========================================================
echo.
echo [1/3] Dang xoa sach du lieu cu va database volume...
docker.exe compose down -v

echo.
echo [2/3] Dang khoi dong lai cum container sach se...
docker.exe compose up -d

echo.
echo [3/3] Dang khoi tao schema va tai khoan admin mau...
docker.exe compose exec api python run_phase2_setup.py

echo.
echo ========================================================
echo   HOAN TAT RESET DU LIEU! SERVER SAN SANG DEMO.
echo   Tai khoan Admin:      admin@hkdn.edu.vn / admin123
echo   Tai khoan Giang vien: lecturer@hkdn.edu.vn / lecturer123
echo ========================================================
pause

