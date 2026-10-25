int counter = 0;

int increment() {
    counter = counter + 1;
    return counter;
}

int main() {
    increment();
    increment();
    return counter;
}
