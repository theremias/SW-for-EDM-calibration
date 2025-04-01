import socket
import time

class Interferometer:
    def __init__(self, ip, port=5001):
        self.ip = ip
        self.port = port
        self.client = None

    def connect(self):
        """Připojení k interferometru"""
        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((self.ip, self.port))
            print(f"Connected to {self.ip}:{self.port}")
        except socket.error as err:
            print(f"Connection error: {err}")
            self.client = None

    def send_command(self, command, timeout=3):
        """Odeslání příkazu a čekání na odpověď (s timeoutem)"""
        if not self.client:
            print("Not connected to interferometer")
            return None

        try:
            self.client.sendall((command + "\r\n\r\n").encode())
            self.client.settimeout(timeout)
            response = self.client.recv(1024).decode().strip()
            return response
        except socket.timeout:
            print("Response timeout")
            return None
        except socket.error as err:
            print(f"Error sending command: {err}")
            return None

    def disconnect(self):
        """Odpojení od interferometru"""
        if self.client:
            self.client.close()
            self.client = None
            print("Connection closed")

    def get_signal_strength(self):
        """Získání síly signálu interferometru"""
        self.connect()
        self.send_command("Connect")
        self.disconnect()
        self.connect()
        signal = self.send_command("SignalStrength")
        self.disconnect()
        self.connect()
        self.send_command("Disconnect")
        self.disconnect()

        if signal:
            try:
                # Extract all characters before "\r\n"
                signal_value = signal.split("\r\n")[0]
                return round(float(signal_value) * 3.226)
            except (ValueError, IndexError) as e:
                print(f"Error parsing signal: {e}")
                return None
        else:
            return None
        
    def get_laser_measurement(self):
        """Get laser measurement"""
        self.connect()
        self.send_command("Connect")
        self.disconnect()
        self.connect()
        self.send_command("ClearErrors")
        self.disconnect()
        self.connect()


    def get_return_value(self, command):
        """Get value IDK TODO"""
        self.connect()
        self.send_command("Connect")
        self.disconnect()
        self.connect()
        value = self.send_command(command)
        self.disconnect()
        self.connect()
        self.send_command("Disconnect")
        self.disconnect()

        if value:
            return value
        else:
            return None

# Použití
ip = "192.168.1.224"  # Změň na správnou IP adresu
interferometer = Interferometer(ip)

signal_strength = interferometer.get_signal_strength()
signal_strength2 = interferometer.get_return_value("SignalStrength")
interferometer.get_return_value("ClearErrors")
laser_measurement = interferometer.get_return_value("GetLaserMeasurement")
if signal_strength2 is not None:
    print(f"Signal strength: {signal_strength2}%")
else:
    print("Failed to get signa strength2")
if laser_measurement is not None:
    print(f"Laser measurement: {laser_measurement}%")
else:
    print("Failed to get laser measurement")
if signal_strength is not None:
    print(f"Signal strength: {signal_strength}%")
else:
    print("Failed to get signal strength")
