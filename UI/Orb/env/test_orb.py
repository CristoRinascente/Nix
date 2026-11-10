import socket

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print("Comandi: show, hide, idle, rest, working, roll, stare, ok, error, move x y, glide x y, quit")
print("Invio vuoto = esci dallo script")
while True:
    cmd = input("> ").strip()
    if not cmd:
        break
    s.sendto(cmd.encode(), ("127.0.0.1", 50555))