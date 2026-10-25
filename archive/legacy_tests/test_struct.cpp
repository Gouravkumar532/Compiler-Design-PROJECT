struct Point {
    int x;
    int y;
};

int main() {
    struct Point p;
    p.x = 10;
    p.y = 20;
    int sum = p.x + p.y;
    return sum;
}
