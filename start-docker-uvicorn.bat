@echo off
cd /d "C:\Users\gabri\Desktop\OSRM Project\Data"
start "OSRM" docker run --rm -t -p 5001:5000 -v "C:\Users\gabri\Desktop\OSRM Project\Data\data:/data" osrm/osrm-backend:v5.22.0 osrm-routed --port 5000 --algorithm mld --max-matching-size 500 /data/sp-recorte.osrm

timeout /t 5 /nobreak >nul

cd /d "C:\Users\gabri\Desktop\rotas_interface"
start "Uvicorn" uvicorn rq_processor_server:app --host 127.0.0.1 --port 5008 --reload

exit
