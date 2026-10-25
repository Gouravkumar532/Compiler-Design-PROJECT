int main() {
    auto square = [](int x) {
        return x * x;
    };

    auto add = [](int a, int b) {
        return a + b;
    };

    int s = square(5);  // 25
    int sum = add(s, 10); // 35

    return sum; // 35
}
