#include <iostream>

int main() {
    int N = 50;
    int a[50];
    int b[50];
    int c[50];
    for (int i = 0; i < N; i++) {
        a[i] = i * 2;
        b[i] = i + 3;
        c[i] = 0;
    }
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            c[i] = c[i] + a[i] * b[j];
        }
    }
    std::cout << "Matrix checksum = " << c[0] << std::endl;
    return 0;
}
