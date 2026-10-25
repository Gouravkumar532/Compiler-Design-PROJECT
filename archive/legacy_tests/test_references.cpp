void increment(int& val) {
    val = val + 1;
}

int main() {
    int a = 10;
    int& ref = a;
    ref = 20;

    increment(a);

    return a;
}
