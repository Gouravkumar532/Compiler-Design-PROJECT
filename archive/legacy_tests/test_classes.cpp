class Counter {
private:
    int count;
public:
    void init(int start) {
        this->count = start;
    }
    void increment() {
        count = count + 1;
    }
    int getCount() {
        return this->count;
    }
};

int main() {
    Counter c;
    c.init(5);
    c.increment();
    c.increment();
    return c.getCount();
}
