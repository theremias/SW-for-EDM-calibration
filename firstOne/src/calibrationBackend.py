from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Protocol
import uuid
from fpdf import FPDF
from fastapi.responses import FileResponse
import os
import zipfile
import pandas as pd
from sqlalchemy import create_engine, Column, String, Float, Table, MetaData
from sqlalchemy.orm import sessionmaker
import socket
import serial
import time
import logging

# ===== LOGGER =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ==== DATABASE ====
DATABASE_URL = "sqlite:///./calibration.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()

measurements_table = Table(
    "measurements",
    metadata,
    Column("id", String, primary_key=True),
    Column("distance_ts", Float),
    Column("distance_ifm", Float),
    Column("difference", Float),
    Column("status", String),
    Column("note", String, nullable=True)
)
metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ==== DEVICE INTERFACES ====
class InterferometerInterface(Protocol):
    def measure(self) -> float:
        ...

class RenishawXL80(InterferometerInterface):
    def __init__(self, host: str, port: int = 23, timeout: float = 2.0, retry: int = 3, retry_delay: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retry = retry
        self.retry_delay = retry_delay
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.connect()

     def connect(self):
        attempts = 0
        while attempts < self.retry:
            try:
                self.sock.connect((self.host, self.port))
                logger.info(f"Connected to Renishaw XL80 at {self.host}:{self.port}")
                return
            except Exception as e:
                attempts += 1
                logger.warning(f"Attempt {attempts}/{self.retry} failed to connect XL80: {e}")
                time.sleep(self.retry_delay)
        logger.error("Exceeded max retries for XL80 connection")
        raise ConnectionError("Unable to connect to Renishaw XL80")

    def measure(self) -> float:
        cmd = "MD?\r\n"  # Example command, adapt to protocol
        for attempt in range(1, self.retry + 1):
            try:
                self.sock.sendall(cmd.encode())
                data = self.sock.recv(1024)
                resp = data.decode().strip()
                value = float(resp)
                return value
            except (socket.error, ValueError) as e:
                logger.warning(f"Measurement attempt {attempt} failed on XL80: {e}")
                if attempt < self.retry:
                    time.sleep(self.retry_delay)
                    self.reconnect()
                else:
                    logger.error("All measurement attempts failed for XL80")
                    raise

    def reconnect(self):
        try:
            self.sock.close()
        except:
            pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.connect()

class TotalStationInterface(Protocol):
    def measure(self) -> float:
        ...

class LeicaTC307(TotalStationInterface):
    def __init__(self, port: str = 'COM1', baudrate: int = 9600, timeout: float = 1.0, retry: int = 3, retry_delay: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retry = retry
        self.retry_delay = retry_delay
        self._connect_serial()

    def _connect_serial(self):
        attempts = 0
        while attempts < self.retry:
            try:
                self.ser = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
                logger.info(f"Opened serial port for Leica TC307: {self.port} @ {self.baudrate}bps")
                return
            except serial.SerialException as e:
                attempts += 1
                logger.warning(f"Attempt {attempts}/{self.retry} failed to open TC307 port: {e}")
                time.sleep(self.retry_delay)
        logger.error("Exceeded max retries for TC307 serial connection")
        raise ConnectionError("Unable to open serial port for Leica TC307")

    def measure(self) -> float:
        cmd = "DIST?\r"  # Adapt to Leica protocol
        for attempt in range(1, self.retry + 1):
            try:
                self.ser.write(cmd.encode())
                line = self.ser.readline().decode().strip()
                value = float(line)
                return value
            except (serial.SerialException, ValueError) as e:
                logger.warning(f"Measurement attempt {attempt} failed on TC307: {e}")
                if attempt < self.retry:
                    time.sleep(self.retry_delay)
                    self._connect_serial()
                else:
                    logger.error("All measurement attempts failed for TC307")
                    raise

# ==== MODELY ====
class ManualInput(BaseModel):
    distance_ts: float
    distance_ifm: float
    note: Optional[str] = None

class MeasurementResult(BaseModel):
    id: str
    distance_ts: float
    distance_ifm: float
    difference: float
    status: str
    note: Optional[str] = None

# ==== KONSTANTY ====
TOLERANCE_MM = 0.5
PDF_FOLDER = "./pdf_reports"
os.makedirs(PDF_FOLDER, exist_ok=True)

# ==== POMOCNÉ FUNKCE ====
def evaluate_measurement(ts: float, ifm: float) -> (float, str):
    diff = ts - ifm
    status = "OK" if abs(diff) <= TOLERANCE_MM else "OUT_OF_TOLERANCE"
    return diff, status

def generate_pdf_report(result: MeasurementResult) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Kalibrační protokol", ln=True, align="C")
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"ID měření: {result.id}", ln=True)
    pdf.cell(200, 10, txt=f"Měření TS: {result.distance_ts} mm", ln=True)
    pdf.cell(200, 10, txt=f"Měření IFM: {result.distance_ifm} mm", ln=True)
    pdf.cell(200, 10, txt=f"Rozdíl: {result.difference:.3f} mm", ln=True)
    pdf.cell(200, 10, txt=f"Stav: {result.status}", ln=True)
    if result.note:
        pdf.cell(200, 10, txt=f"Poznámka: {result.note}", ln=True)
    file_path = os.path.join(PDF_FOLDER, f"report_{result.id}.pdf")
    pdf.output(file_path)
    return file_path

def export_all_to_excel(path: str):
    with engine.connect() as conn:
        df = pd.read_sql_table("measurements", conn)
        df.to_excel(path, index=False)

def zip_all_reports(zip_path: str):
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        with engine.connect() as conn:
            result = conn.execute(measurements_table.select()).fetchall()
            for row in result:
                measurement = MeasurementResult(**row._asdict())
                pdf_path = generate_pdf_report(measurement)
                zipf.write(pdf_path, arcname=os.path.basename(pdf_path))

# ==== ENDPOINTY ====
@app.post("/manual-input", response_model=MeasurementResult)
def manual_input(data: ManualInput):
    measurement_id = str(uuid.uuid4())
    diff, status = evaluate_measurement(data.distance_ts, data.distance_ifm)
    result = MeasurementResult(
        id=measurement_id,
        distance_ts=data.distance_ts,
        distance_ifm=data.distance_ifm,
        difference=diff,
        status=status,
        note=data.note
    )
    with engine.begin() as conn:
        conn.execute(measurements_table.insert().values(**result.dict()))
    return result

@app.get("/results/{measurement_id}", response_model=MeasurementResult)
def get_result(measurement_id: str):
    with engine.connect() as conn:
        row = conn.execute(measurements_table.select().where(measurements_table.c.id == measurement_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Measurement not found")
        return MeasurementResult(**row._asdict())

@app.get("/results", response_model=list[MeasurementResult])
def get_all_results():
    with engine.connect() as conn:
        result = conn.execute(measurements_table.select()).fetchall()
        return [MeasurementResult(**row._asdict()) for row in result]

@app.get("/results/{measurement_id}/report")
def get_pdf_report(measurement_id: str):
    with engine.connect() as conn:
        row = conn.execute(measurements_table.select().where(measurements_table.c.id == measurement_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Measurement not found")
        result = MeasurementResult(**row._asdict())
        pdf_path = generate_pdf_report(result)
        return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))

@app.get("/results/export/excel")
def export_excel():
    path = "./calibration_results.xlsx"
    export_all_to_excel(path)
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="calibration_results.xlsx")

@app.get("/results/export/zip")
def export_zip():
    zip_path = "./all_reports.zip"
    zip_all_reports(zip_path)
    return FileResponse(zip_path, media_type="application/zip", filename="all_reports.zip")
