class Animal {
public:
    virtual int speak() {
        return 1;
    }
};

class Dog : public Animal {
public:
    int speak() override {
        return 2;
    }
};

class Cat : public Animal {
public:
    int speak() override {
        return 3;
    }
};

int main() {
    Dog d;
    Cat c;

    Animal* a1 = (Animal*)&d;
    Animal* a2 = (Animal*)&c;

    int r1 = a1->speak(); // 2
    int r2 = a2->speak(); // 3

    return r1 + r2; // 5
}
