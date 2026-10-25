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
        this->x = 0;
        this->y = 0;
    }
    int getX() {
        return this->x;
    }
    int getY() {
        return this->y;
    }
};

int main() {
    int* pInt = new int(100);
    int val = *pInt;
    delete pInt;

    Point* p = new Point(12, 34);
    int sum = p->getX() + p->getY();
    delete p;

    return val + sum;
}
