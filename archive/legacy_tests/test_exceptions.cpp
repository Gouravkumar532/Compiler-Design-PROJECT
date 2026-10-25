int test_func(int x) {
    if (x < 0) {
        throw 99;
    }
    return x * 2;
}

int main() {
    int result = 0;

    try {
        int a = test_func(5);
        result = a;
        throw 42;
        result = 1000; // Unreachable
    } catch (int e) {
        result = result + e; // 10 + 42 = 52
    }

    return result; // 52
}
