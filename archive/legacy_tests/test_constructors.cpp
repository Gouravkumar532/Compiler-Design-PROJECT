int destroyed_flag = 0;

class Point {
private:
    int x;
    int y;
public:
    Point(int a, int b) {
        this->x = a;
        this->y = b;
    }
    ~Point() {
        destroyed_flag = 1;
    }
    int sum() {
        return x + y;
    }
};

int main() {
    Point p(15, 27);
    int total = p.sum();
    return total;
}
