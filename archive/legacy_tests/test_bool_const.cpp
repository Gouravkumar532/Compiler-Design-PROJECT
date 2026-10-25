int main() {
    bool flag = true;
    bool is_done = false;
    const int max_limit = 100;
    int count = 0;

    if (flag && !is_done) {
        count = count + 10;
    }

    if (count < max_limit) {
        return count;
    }
    return 0;
}
