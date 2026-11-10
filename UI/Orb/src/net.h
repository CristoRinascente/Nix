#pragma once

bool netInit(int port);
int  netPoll(char* buf, int cap);   // restituisce 0 se non ci sono messaggi
void netClose();