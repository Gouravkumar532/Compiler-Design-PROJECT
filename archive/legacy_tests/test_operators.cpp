class Vector2 {
public:
    int x;
    int y;
    Vector2(int a, int b) {
        this->x = a;
        this->y = b;
    }
    int operator+(int val) {
        return this->x + this->y + val;
    }
    bool operator==(int target) {
        return (this->x + this->y) == target;
    }
};

int main() {
    int shifted = 1 << 3;
    int right_shifted = shifted >> 1;

    Vector2 v(10, 20);
    int total = v + shifted;
    bool matches = (v == 30);

    if (matches) {
        return total + right_shifted;
    }
    return 0;
}
