int multiply(int a, int b) {
    return a * b;
}

int multiply(int a, int b, int c) {
    return a * b * c;
}

double multiply(double a, double b) {
    return a * b;
}

int main() {
    int r1 = multiply(3, 4);
    int r2 = multiply(2, 3, 4);
    double r3 = multiply(2.5, 2.0);

    int total = r1 + r2 + (int)r3;
    return total;
}
