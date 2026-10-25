int factorial_helper(int n, int acc) {
    if (n <= 1) {
        return acc;
    }
    // Tail call returning directly into current frame
    return factorial_helper(n - 1, acc * n);
}

int main() {
    int res = factorial_helper(5, 1);
    return res;
}
