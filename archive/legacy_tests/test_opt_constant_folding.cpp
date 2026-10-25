int main() {
    // Arithmetic constant folding
    int a = 10 + 20 * 2; // 50
    int b = (100 - 40) / 3; // 20
    int c = 17 % 5; // 2

    // Bitwise constant folding
    int d = 1 << 3; // 8
    int e = 15 & 7; // 7

    // Comparison and ternary constant folding
    int f = (a > b) ? 100 : 200; // 100
    int g = (5 == 5) && (10 != 2); // 1

    // Algebraic identity simplifications
    int h = a + 0; // a
    int i = b * 1; // b

    int sum = a + b + c + d + e + f + g + h + i;
    return sum;
}
