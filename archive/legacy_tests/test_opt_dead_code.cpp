int compute() {
    int x = 10;
    if (0) {
        x = 999; // Dead branch: eliminated
    } else {
        x = x + 5; // Taken branch
    }

    if (1) {
        x = x * 2; // Always taken: unwrapped
    }

    return x;
    x = 42; // Unreachable statement: pruned
}

int main() {
    int res = compute();
    return res;
}
