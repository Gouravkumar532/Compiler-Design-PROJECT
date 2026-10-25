namespace Math {
    int add(int a, int b) {
        return a + b;
    }
    int square(int x) {
        return x * x;
    }
}

int main() {
    int sum = Math::add(10, 20);

    using namespace Math;
    int sq = square(5);

    return sum + sq;
}
