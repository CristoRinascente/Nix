#include "net.h"
#include <winsock2.h>
#include <ws2tcpip.h>

static SOCKET gSock = INVALID_SOCKET;

bool netInit(int port) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;

    gSock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (gSock == INVALID_SOCKET) return false;

    u_long nonBlocking = 1;
    ioctlsocket(gSock, FIONBIO, &nonBlocking);

    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons((u_short)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);   // solo questo PC
    if (bind(gSock, (sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) return false;
    return true;
}

int netPoll(char* buf, int cap) {
    if (gSock == INVALID_SOCKET) return 0;
    int n = recvfrom(gSock, buf, cap - 1, 0, nullptr, nullptr);
    if (n <= 0) return 0;
    buf[n] = 0;
    return n;
}

void netClose() {
    if (gSock != INVALID_SOCKET) closesocket(gSock);
    WSACleanup();
}