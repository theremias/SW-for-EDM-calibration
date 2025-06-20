from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Protocol
import uuid
from fpdf import FPDF
from fastapi.responses import FileResponse
import os
import zipfile
import pandas as pd
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, Table, MetaData
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import datetime
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
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    device_ts = Column(String)
    device_ifm = Column(String)
    operator = Column(String)

    measurements = relationship("Measurement", back_populates="session")

class Measurement(Base):
    __tablename__ = 'measurements'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    distance_ts = Column(Float)
    distance_ifm = Column(Float)
    difference = Column(Float)
    status = Column(String)
    note = Column(Text)
    session_id = Column(String, ForeignKey("sessions.id"))

    session = relationship("Session", back_populates="measurements")

Base.metadata.create_all(engine)

# ==== KONFIGURACE ====
class CalibrationConfig(BaseModel):
    tol_ok: float = 0.5            # do této odchylky mm je OK
    tol_suspicious: float = 1.0    # do této odchylky mm je "PODEZŘELÉ"

config = CalibrationConfig()

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

class HomingResult(BaseModel):
    offset_ts: float

class MeasurementResult(BaseModel):
    id: str
    offset_ts: float
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

# ==== OVLÁDÁNÍ KROKOVÉHO MOTORU A VOZÍKU ====
class StepperMotorInterface(Protocol):
    """
    Rozhraní pro krokový motor ovládající vozík.
    """
    def connect(self) -> None:
        ...
    def move_steps(self, steps: int, speed: float) -> None:
        ...
    def disconnect(self) -> None:
        ...

class RailCarriageController:
    """
    Řídí pohyb vozíku s odraznými hranoly po kolejnici pomocí krokového motoru.
    """
    def __init__(self, motor: StepperMotorInterface, steps_per_mm: float):
        self.motor = motor
        self.steps_per_mm = steps_per_mm
        self.current_position_mm = 0.0

    def initialize(self) -> None:
        """
        Připraví komunikaci s motorem a kalibruje referenční bod (origin).
        Např. pohyb do koncové spínače.
        """
        self.motor.connect()
        # TODO: implement homing sequence, např. pohyb několika mm dozadu dokud nedojde ke spínači
        # self.current_position_mm = 0.0
        # logger.info("Homing completed, origin set to 0 mm")

    def move_to(self, position_mm: float, speed: float = 10.0) -> None:
        """
        Přemístí vozík na zadanou pozici v mm.
        """
        target_steps = int((position_mm - self.current_position_mm) * self.steps_per_mm)
        logger.info(f"Moving carriage from {self.current_position_mm}mm to {position_mm}mm ({target_steps} steps)")
        self.motor.move_steps(target_steps, speed)
        self.current_position_mm = position_mm

    def get_position(self) -> float:
        """
        Vrací aktuální polohu vozíku v mm.
        """
        return self.current_position_mm

    def shutdown(self) -> None:
        """
        Ukončí komunikaci s motorem.
        """
        self.motor.disconnect()

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
