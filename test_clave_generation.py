"""
Test de generación de claves personalizadas
"""
import random
import string

def generar_clave_personalizada():
    """Genera clave de 6 caracteres: 3 letras y 3 números combinados aleatoriamente"""
    letras = [random.choice(string.ascii_lowercase) for _ in range(3)]
    numeros = [random.choice(string.digits) for _ in range(3)]
    caracteres = letras + numeros
    random.shuffle(caracteres)  # Mezclar letras y números
    return ''.join(caracteres)

print("=" * 50)
print("EJEMPLOS DE CLAVES GENERADAS")
print("=" * 50)
print("Formato: 3 letras + 3 números (mezclados)")
print()

for i in range(10):
    clave = generar_clave_personalizada()
    print(f"Clave {i+1:2d}: {clave}")

print()
print("✅ Las claves tienen 6 caracteres")
print("✅ Contienen 3 letras y 3 números")
print("✅ El orden está mezclado aleatoriamente")
print("=" * 50)