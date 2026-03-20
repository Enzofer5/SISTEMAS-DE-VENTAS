from flask import Flask, render_template, request, redirect, session, url_for
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = "clave_super_segura"


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="43772036",
        database="registro_ventas"
    )


# ========================
# DECORADOR DE ROLES
# ========================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):

            if "rol" not in session:
                return redirect(url_for("login"))

            if session["rol"] not in roles:
                return "No tienes permiso"

            return f(*args, **kwargs)

        return wrapped
    return decorator


# ========================
# LOGIN
# ========================

@app.route("/", methods=["GET","POST"])
def login():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verificar si existe dueño
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE rol='dueno'")
    existe_dueno = cursor.fetchone()[0]

    conn.close()

    # Si no hay dueño, ir a crear dueño
    if existe_dueno == 0:
        return redirect("/crear_dueno")

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM usuarios WHERE email=%s",(email,))
        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user[3], password):

            session["user_id"] = user[0]
            session["rol"] = user[4]
            session["empresa_id"] = user[6]

            return redirect("/dashboard")

        return "Credenciales incorrectas"

    return render_template("login.html")

# ========================
# CREAR DUEÑO
# ========================

@app.route("/crear_dueno", methods=["GET","POST"])
def crear_dueno():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verificar si ya existe dueño
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE rol='dueno'")
    existe = cursor.fetchone()[0]

    if existe > 0:
        conn.close()
        return redirect("/")

    if request.method == "POST":

        nombre_empresa = request.form["empresa"]
        nombre = request.form["nombre"]
        email = request.form["email"]
        password = request.form["password"]

        password_hash = generate_password_hash(password)

        # Crear empresa
        cursor.execute("""
        INSERT INTO empresas (nombre,email,fecha_vencimiento)
        VALUES (%s,%s,DATE_ADD(CURDATE(),INTERVAL 30 DAY))
        """,(nombre_empresa,email))

        empresa_id = cursor.lastrowid

        # Crear dueño
        cursor.execute("""
        INSERT INTO usuarios (nombre,email,password,rol,empresa_id)
        VALUES (%s,%s,%s,'dueno',%s)
        """,(nombre,email,password_hash,empresa_id))

        conn.commit()
        conn.close()

        return redirect("/")

    conn.close()

    return render_template("crear_dueno.html")


# ========================
# REGISTRO EMPRESA
# ========================

@app.route("/registro_empresa", methods=["GET", "POST"])
def registro_empresa():

    if request.method == "POST":

        empresa = request.form["empresa"]
        email = request.form["email"]
        password = request.form["password"]
        nombre = request.form["nombre"]

        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO empresas (nombre,email,fecha_vencimiento)
        VALUES (%s,%s,DATE_ADD(CURDATE(), INTERVAL 30 DAY))
        """, (empresa, email))

        empresa_id = cursor.lastrowid

        cursor.execute("""
        INSERT INTO usuarios (nombre,email,password,rol,empresa_id)
        VALUES (%s,%s,%s,'dueno',%s)
        """, (nombre, email, password_hash, empresa_id))

        conn.commit()
        conn.close()

        return "Empresa creada correctamente"

    return render_template("registro_empresa.html")


# ======================
# DASHBOARD
# ======================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    empresa_id = session["empresa_id"]

    # ======================
    # STOCK BAJO
    # ======================

    cursor.execute("""
    SELECT nombre, stock
    FROM productos
    WHERE empresa_id=%s AND stock <=3 AND activo=1
    """,(empresa_id,))

    stock_bajo = cursor.fetchall()


    # ======================
    # PRODUCTO MAS VENDIDO
    # ======================

    cursor.execute("""
    SELECT p.nombre, SUM(v.cantidad) total
    FROM ventas v
    JOIN productos p ON v.producto_id = p.id
    WHERE v.empresa_id=%s
    GROUP BY p.nombre
    ORDER BY total DESC
    LIMIT 1
    """,(empresa_id,))

    producto_top = cursor.fetchone()


    # ======================
    # GANANCIAS
    # ======================

    cursor.execute("""
    SELECT 
    SUM(v.total) ventas,
    SUM(v.cantidad * p.precio_compra) costo
    FROM ventas v
    JOIN productos p ON v.producto_id = p.id
    WHERE v.empresa_id=%s
    """,(empresa_id,))

    datos = cursor.fetchone()

    ventas_totales = datos["ventas"] or 0
    costo_total = datos["costo"] or 0
    ganancia_real = ventas_totales - costo_total


    # ======================
    # RANKING VENDEDORES
    # ======================

    cursor.execute("""
    SELECT u.nombre, SUM(v.total) total
    FROM ventas v
    JOIN usuarios u ON v.usuario_id = u.id
    WHERE v.empresa_id=%s
    GROUP BY u.nombre
    ORDER BY total DESC
    LIMIT 5
    """,(empresa_id,))

    ranking = cursor.fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        rol=session["rol"],
        stock_bajo=stock_bajo,
        producto_top=producto_top,
        ventas_totales=ventas_totales,
        costo_total=costo_total,
        ganancia_real=ganancia_real,
        ranking=ranking
    )


# ========================
# PRODUCTOS + CARGAR STOCK
# ========================

@app.route("/productos", methods=["GET", "POST"])
@role_required("dueno")
def productos():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        accion = request.form["accion"]

        # ========================
        # CREAR PRODUCTO
        # ========================
        if accion == "crear":

            nombre = request.form["nombre"]
            precio_compra = request.form["precio_compra"]
            precio_venta = request.form["precio_venta"]
            comision = request.form["comision"]

            cursor.execute("""
            INSERT INTO productos
            (nombre,precio_compra,precio_venta,comision,stock,empresa_id,activo)
            VALUES (%s,%s,%s,%s,0,%s,1)
            """,(nombre,precio_compra,precio_venta,comision,session["empresa_id"]))

            conn.commit()

        # ========================
        # CARGAR STOCK
        # ========================
        if accion == "stock":

            producto_id = request.form["producto_id"]
            cantidad = int(request.form["cantidad"])

            cursor.execute("""
            UPDATE productos
            SET stock = stock + %s
            WHERE id = %s AND empresa_id=%s
            """,(cantidad,producto_id,session["empresa_id"]))

            # registrar movimiento
            cursor.execute("""
            INSERT INTO movimientos_stock
            (producto_id,tipo,cantidad,empresa_id)
            VALUES (%s,'compra',%s,%s)
            """,(producto_id,cantidad,session["empresa_id"]))

            conn.commit()

    # SOLO PRODUCTOS ACTIVOS
    cursor.execute("""
    SELECT * FROM productos
    WHERE empresa_id=%s AND activo=1
    """,(session["empresa_id"],))

    productos = cursor.fetchall()

    conn.close()

    return render_template("productos.html", productos=productos)

# ========================
# EDITAR PRODUCTO
# ========================

@app.route("/editar_producto/<int:id>", methods=["GET","POST"])
@role_required("dueno")
def editar_producto(id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        precio_compra = request.form["precio_compra"]
        precio_venta = request.form["precio_venta"]
        comision = request.form["comision"]
        stock = request.form["stock"]

        cursor.execute("""
        UPDATE productos
        SET precio_compra=%s,
            precio_venta=%s,
            comision=%s,
            stock=%s
        WHERE id=%s AND empresa_id=%s
        """,(precio_compra,precio_venta,comision,stock,id,session["empresa_id"]))

        conn.commit()
        conn.close()

        return redirect("/productos")

    cursor.execute("""
    SELECT * FROM productos
    WHERE id=%s AND empresa_id=%s
    """,(id,session["empresa_id"]))

    producto = cursor.fetchone()

    conn.close()

    return render_template("editar_producto.html", producto=producto)



# ========================
# CREAR VENDEDOR
# ========================

@app.route("/crear_vendedor", methods=["GET","POST"])
@role_required("dueno")
def crear_vendedor():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        nombre = request.form["nombre"]
        email = request.form["email"]
        password = request.form["password"]

        password_hash = generate_password_hash(password)

        cursor.execute("""
        INSERT INTO usuarios (nombre,email,password,rol,empresa_id)
        VALUES (%s,%s,%s,'vendedor',%s)
        """,(nombre,email,password_hash,session["empresa_id"]))

        conn.commit()

        return "Vendedor creado correctamente"
    
    

    conn.close()

    return render_template("crear_vendedor.html")

# ========================
# ELIMINAR VENDEDOR
# ========================

@app.route("/eliminar_vendedor", methods=["GET","POST"])
@role_required("dueno")
def eliminar_vendedor():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT * FROM usuarios
    WHERE rol='vendedor'
    AND empresa_id=%s
    AND activo=1
    """,(session["empresa_id"],))

    vendedores = cursor.fetchall()

    if request.method == "POST":

        vendedor_id = request.form["vendedor_id"]

        cursor.execute("""
        UPDATE usuarios
        SET activo = 0
        WHERE id = %s
        """,(vendedor_id,))

        conn.commit()

        return "Vendedor eliminado"

    conn.close()

    return render_template("eliminar_vendedor.html", vendedores=vendedores)

# ========================
# CREAR LIDER
# ========================

@app.route("/crear_lider", methods=["GET","POST"])
@role_required("dueno")
def crear_lider():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        nombre = request.form["nombre"]
        email = request.form["email"]
        password = request.form["password"]

        password_hash = generate_password_hash(password)

        cursor.execute("""
        INSERT INTO usuarios (nombre,email,password,rol,empresa_id)
        VALUES (%s,%s,%s,'lider',%s)
        """,(nombre,email,password_hash,session["empresa_id"]))

        conn.commit()

        return "Líder creado correctamente"

    conn.close()

    return render_template("crear_lider.html")

# ========================
# ELIMINAR LIDER
# ========================

@app.route("/eliminar_lider", methods=["GET","POST"])
@role_required("dueno")
def eliminar_lider():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT * FROM usuarios
    WHERE rol='lider'
    AND empresa_id=%s
    AND activo=1
    """,(session["empresa_id"],))

    lideres = cursor.fetchall()

    if request.method == "POST":

        lider_id = request.form["lider_id"]

        cursor.execute("""
        UPDATE usuarios
        SET activo = 0
        WHERE id=%s
        """,(lider_id,))

        conn.commit()

        return "Líder eliminado"

    conn.close()

    return render_template("eliminar_lider.html", lideres=lideres)


# ========================
# REGISTRAR VENTA
# ========================

@app.route("/venta", methods=["GET", "POST"])
def venta():

    if "user_id" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM productos WHERE empresa_id=%s",
                   (session["empresa_id"],))

    productos = cursor.fetchall()

    if request.method == "POST":

        producto_id = request.form["producto_id"]
        cantidad = int(request.form["cantidad"])

        cursor.execute("SELECT * FROM productos WHERE id=%s", (producto_id,))
        producto = cursor.fetchone()

        if producto["stock"] < cantidad:
            return "Stock insuficiente"

        precio_unitario = producto["precio_venta"]
        total = precio_unitario * cantidad

        # Crear venta
        cursor.execute("""
        INSERT INTO ventas
        (producto_id,usuario_id,empresa_id,cantidad,precio_unitario,total)
        VALUES (%s,%s,%s,%s,%s,%s)
        """, (producto_id, session["user_id"], session["empresa_id"],
              cantidad, precio_unitario, total))

        venta_id = cursor.lastrowid

        # Comisión
        comision_real = (producto["comision"] / 100) * total

        cursor.execute("""
        INSERT INTO detalle_venta
        (venta_id,producto_id,cantidad,precio_unitario,comision_aplicada)
        VALUES (%s,%s,%s,%s,%s)
        """, (venta_id, producto_id, cantidad, precio_unitario, comision_real))

        # Descontar stock
        cursor.execute("""
        UPDATE productos
        SET stock = stock - %s
        WHERE id = %s
        """, (cantidad, producto_id))

        # Registrar movimiento stock
        cursor.execute("""
        INSERT INTO movimientos_stock
        (producto_id,tipo,cantidad,empresa_id)
        VALUES (%s,'venta',%s,%s)
        """,(producto_id,cantidad,session["empresa_id"]))

        conn.commit()
        conn.close()

        return redirect("/dashboard")

    conn.close()
    return render_template("venta.html", productos=productos)


# ========================
# LISTAR VENTAS
# ========================

@app.route("/ventas")
def listar_ventas():

    if "user_id" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT v.id,v.fecha,v.total,u.nombre as vendedor
    FROM ventas v
    JOIN usuarios u ON v.usuario_id = u.id
    WHERE v.empresa_id = %s
    ORDER BY v.fecha DESC
    """, (session["empresa_id"],))

    ventas = cursor.fetchall()

    conn.close()

    return render_template("ventas.html", ventas=ventas)


# ========================
# DETALLE VENTA
# ========================

@app.route("/detalle_venta/<int:venta_id>")
def detalle_venta(venta_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT p.nombre,d.cantidad,d.precio_unitario,d.comision_aplicada
    FROM detalle_venta d
    JOIN productos p ON d.producto_id = p.id
    WHERE d.venta_id=%s
    """, (venta_id,))

    detalles = cursor.fetchall()

    conn.close()

    return render_template("detalle_venta.html", detalles=detalles)

# ========================
# MIS VENTAS
# ========================
@app.route("/mis_ventas")
@role_required("vendedor")
def mis_ventas():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT v.id, p.nombre, v.cantidad, v.total, v.fecha
    FROM ventas v
    JOIN productos p ON v.producto_id = p.id
    WHERE v.usuario_id = %s
    """,(session["user_id"],))

    ventas = cursor.fetchall()

    conn.close()

    return render_template("mis_ventas.html", ventas=ventas)

# ========================
# VENTAS DEL EQUIPO
# ========================
@app.route("/ventas_equipo")
@role_required("dueno","lider")
def ventas_equipo():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT u.nombre as vendedor, SUM(v.total) as total_vendido
    FROM ventas v
    JOIN usuarios u ON v.usuario_id = u.id
    WHERE v.empresa_id = %s
    GROUP BY u.nombre
    """,(session["empresa_id"],))

    ventas = cursor.fetchall()

    conn.close()

    return render_template("ventas_equipo.html", ventas=ventas)

# ========================
# STOCK
# ========================

@app.route("/stock")
def stock():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT nombre,stock,precio_compra,precio_venta
    FROM productos
    WHERE empresa_id=%s
    """, (session["empresa_id"],))

    productos = cursor.fetchall()

    conn.close()

    return render_template("stock.html", productos=productos)

# ========================
# VER GANANCIAS
# ========================

@app.route("/ganancias")
@role_required("dueno")
def ganancias():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT 
        v.id,
        p.nombre AS producto,
        u.nombre AS vendedor,
        v.cantidad,
        v.total,
        v.fecha
    FROM ventas v
    JOIN productos p ON v.producto_id = p.id
    JOIN usuarios u ON v.usuario_id = u.id
    WHERE v.empresa_id = %s
    ORDER BY v.fecha DESC
    """,(session["empresa_id"],))

    ventas = cursor.fetchall()

    cursor.execute("""
    SELECT SUM(total) AS total_ventas
    FROM ventas
    WHERE empresa_id = %s
    """,(session["empresa_id"],))

    total = cursor.fetchone()

    conn.close()

    return render_template("ganancias.html", ventas=ventas, total=total)


# ========================
# MIS COMISIONES
# ========================

@app.route("/mis_comisiones")
@role_required("vendedor")
def mis_comisiones():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT 
    p.nombre,
    d.cantidad,
    d.comision_aplicada,
    v.fecha
    FROM detalle_venta d
    JOIN ventas v ON d.venta_id = v.id
    JOIN productos p ON d.producto_id = p.id
    WHERE v.usuario_id=%s
    """, (session["user_id"],))

    ventas = cursor.fetchall()

    cursor.execute("""
    SELECT SUM(d.comision_aplicada) as total
    FROM detalle_venta d
    JOIN ventas v ON d.venta_id=v.id
    WHERE v.usuario_id=%s
    """, (session["user_id"],))

    total = cursor.fetchone()

    conn.close()

    return render_template("mis_comisiones.html", ventas=ventas, total=total)

# ========================
# PAGOS A VENDEDORES
# ========================

@app.route("/pagos")
@role_required("dueno")
def pagos():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT 
    u.nombre as vendedor,
    p.monto,
    p.tipo,
    p.fecha
    FROM pagos_vendedores p
    JOIN usuarios u ON p.vendedor_id = u.id
    WHERE p.empresa_id = %s
    ORDER BY p.fecha DESC
    """,(session["empresa_id"],))

    pagos = cursor.fetchall()

    conn.close()

    return render_template("pagos.html", pagos=pagos)

# ========================
# LOGOUT
# ========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)