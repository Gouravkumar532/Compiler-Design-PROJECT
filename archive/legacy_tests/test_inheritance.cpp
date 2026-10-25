class Vehicle {
public:
    int speed;

    Vehicle() {
        this->speed = 60;
    }

    int getSpeed() {
        return this->speed;
    }
};

class Car : public Vehicle {
public:
    int wheels;

    Car() {
        this->wheels = 4;
    }

    int getWheels() {
        return this->wheels;
    }
};

int main() {
    Car c;
    int s = c.getSpeed();
    int w = c.getWheels();
    return s + w; // 60 + 4 = 64
}
