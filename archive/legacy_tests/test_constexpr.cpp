constexpr int multiply(int a, int b) {
    return a * b;
}

int main() {
    constexpr int base = 10;
    constexpr int scale = 5;
    constexpr int total = multiply(base, scale); // Compile-time evaluated to 50
    return total;
}
