template <typename T>
T add(T a, T b) {
    return a + b;
}

template <typename T>
class Box {
public:
    T value;

    Box(T val) {
        this->value = val;
    }

    T getValue() {
        return this->value;
    }
};

int main() {
    int sum = add(10, 20); // 30

    Box<int> b(100);
    int val = b.getValue(); // 100

    return sum + val; // 130
}
