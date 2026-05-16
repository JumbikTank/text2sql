import dis
import inspect

a = []

print("GLOBAL a id:", id(a))
print("GLOBAL a value:", a)
print("-" * 50)

def my_fn():
    print("\n[my_fn] ENTER")
    print("[my_fn] globals()['a'] id:", id(globals()["a"]))
    print("[my_fn] locals():", locals())
    a.append(1)
    print("[my_fn] after append, a:", a)
    print("[my_fn] EXIT")

def my_fn2():
    print("\n[my_fn2] ENTER")
    a = [1]
    print("[my_fn2] local a id:", id(a))
    print("[my_fn2] locals():", locals())
    print("[my_fn2] EXIT")

# --- BEFORE CALLS ---
print("my_fn.__closure__:", my_fn.__closure__)
print("my_fn2.__closure__:", my_fn2.__closure__)
print("-" * 50)

print("BYTECODE my_fn")
dis.dis(my_fn)
print("-" * 50)

print("BYTECODE my_fn2")
dis.dis(my_fn2)
print("-" * 50)

# --- EXECUTION ---
a.append(3)
print("After a.append(3), GLOBAL a:", a)

my_fn()
my_fn2()

print("\nFINAL GLOBAL a:", a)
print("FINAL GLOBAL a id:", id(a))
