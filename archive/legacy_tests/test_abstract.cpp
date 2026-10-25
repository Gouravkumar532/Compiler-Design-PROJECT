class Shape {
public:
    virtual int area() = 0;
};

class Rectangle : public Shape {
public:
    int width;
    int height;

    Rectangle(int w, int h) {
        this->width = w;
        this->height = h;
    }

    int area() override {
        return this->width * this->height;
    }
};

int main() {
    Rectangle r(4, 5);
    Shape* s = (Shape*)&r;
    int a = s->area();
    return a; // 20
}
