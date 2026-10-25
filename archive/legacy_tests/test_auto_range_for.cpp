int main() {
    auto a = 10;
    auto b = 20;

    int arr[5] = {1, 2, 3, 4, 5};
    int sum = 0;

    for (auto val : arr) {
        sum = sum + val;
    }

    return a + b + sum; // 10 + 20 + 15 = 45
}
