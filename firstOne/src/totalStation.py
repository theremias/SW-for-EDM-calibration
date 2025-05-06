import serial
with serial.Serial() as ser:
    ser.baudrate = 19200
    ser.port = 'COM3'  # Replace with your port
    ser.timeout = 2
    ser.open()
    ser.write(b'GET/M/WI31\r\n\r\n')
    bs = ser.read(100)
    print(bs)
    ser.close()