#include <iostream>

int fib(int n) {
    if (n <= 1) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

int main() {
    int result = fib(32);
    std::cout << "Fibonacci(32) = " << result << std::endl;
    return 0;
}
