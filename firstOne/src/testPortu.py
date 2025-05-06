import socket

def is_port_open(ip, port):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((ip, port))
        return True
    except:
        return False
    finally:
        s.close()

ip = "192.168.1.28"
port = 10002
for port in range(1230, 1236):
    print(f"Kontroluji port {port} na {ip}...")
    if is_port_open(ip, port):
        print(f"Port {port} na {ip} je otevřený.")
    else:
        print(f"Port {port} na {ip} je ZAVŘENÝ nebo blokovaný.")