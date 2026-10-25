#include <iostream>

int compute() {
    int total = 0;
    for (int i = 0; i < 500000; i++) {
        int k = (10 + 20 * 3) / 2;
        total += k % 7;
    }
    return total;
}

int main() {
    int res = compute();
    std::cout << "Computed: " << res << std::endl;
    return 0;
}
