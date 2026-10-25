int main() {
    int sum = 0;
    for (int i = 0; i < 10; i = i + 1) {
        if (i % 2 == 0) {
            sum = sum + i;
        } else {
            sum = sum + 1;
        }
    }
    
    int j = 5;
    while (j > 0) {
        j = j - 1;
    }
    return sum;
}
