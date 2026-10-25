void set_value(int* ptr, int val) {
    *ptr = val;
}

int main() {
    int x = 10;
    int* p = &x;
    
    // Dereference read
    int initial = *p;
    
    // Dereference write
    *p = 42;
    
    // Pointer via function
    set_value(p, 99);
    
    return *p;
}
