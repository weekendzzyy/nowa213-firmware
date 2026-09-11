import serial.tools.list_ports as lp
ports = lp.comports()
if not ports:
    print("NO PORTS FOUND")
for p in ports:
    print(p.device, "|", p.description, "|", p.hwid)
