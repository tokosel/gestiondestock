from flask import Flask, render_template,jsonify, request, redirect, url_for, flash, session
from flask_pymongo import PyMongo
from pymongo import MongoClient
import datetime
from datetime import datetime
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pandas as pd
from io import BytesIO
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from flask import send_file
from fpdf import FPDF
from functools import wraps
app = Flask(__name__)
#app.config["MONGO_URI"] = "mongodb://localhost:27017/stock_management"
#app.config["SECRET_KEY"] = "super_secret_key"
app.config["MONGO_URI"] = "mongodb+srv://tokodev:passer123@stock.mglx8.mongodb.net/?retryWrites=true&w=majority&appName=Stock"
app.config["SECRET_KEY"] = "super_secret_key"
mongo = PyMongo(app)
db_users = mongo.db.users
db_fournisseurs = mongo.db.fournisseurs
db_categories = mongo.db.categories
db_produits = mongo.db.produits
db_achats = mongo.db.achats
db_ventes = mongo.db.ventes
app.config['STATIC_FOLDER'] = 'static'

# Décorateur pour vérifier si l'utilisateur est connecté
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Décorateur pour restreindre l'accès à certaines routes
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('user_role') != 'admin':
            return redirect(url_for('index', access_denied=True))
        return f(*args, **kwargs)
    return decorated_function
@app.before_request
def add_access_denied_message():
    if request.args.get('access_denied') == 'True':
        session['access_denied_message'] = "Accès refusé : autorisation nécessaire."
    else:
        session.pop('access_denied_message', None)

# Page de connexion
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = db_users.find_one({"email": email})

        if user and check_password_hash(user['mot_de_passe'], password):
            if user['statut'] == 'actif':
                session['user_id'] = str(user['_id'])
                session['user_name'] = user['nom']
                session['user_role'] = user.get('role', 'user')
                return jsonify({"status": "success", "message": "Connexion réussie!"})
            else:
                return jsonify({"status": "error", "message": "Compte a été désactivé. Veuillez contacter l'administrateur."})
        else:
            return jsonify({"status": "error", "message": "Email ou mot de passe incorrect."})

    return render_template('login.html')

# Page de déconnexion
@app.route('/logout')
def logout():
    session.clear()
    flash('Vous avez été déconnecté avec succès.', 'info')
    return redirect(url_for('login'))

#Conversion
def convert_objectid_to_str(data):
    if isinstance(data, list):
        return [convert_objectid_to_str(item) for item in data]
    elif isinstance(data, dict):
        return {k: convert_objectid_to_str(v) for k, v in data.items()}
    elif isinstance(data, ObjectId):
        return str(data)
    return data

#Tableau de bord
@app.route('/')
@login_required
def index():
    # 1. Total des produits (produits actifs seulement)
    total_produits = db_produits.count_documents({"statut": "actif"})
    
    # 2. Nombre de produits en faible quantité (quantité inférieure à un seuil, ex: < 5)
    seuil_critique = 5
    produits_faible_quantite = db_produits.count_documents({"statut": "actif", "quantite": {"$lt": seuil_critique}})
    
    # 3. Total des ventes
    total_ventes = db_ventes.aggregate([
        {"$group": {"_id": None, "total_ventes": {"$sum": "$quantite_achetee"}}}
    ])
    total_ventes = list(total_ventes)[0]['total_ventes'] if total_ventes else 0
    
    # 4. Chiffre d'affaires total (quantité * prix de vente)
    chiffre_affaires_total = db_ventes.aggregate([
        {"$group": {"_id": None, "total_revenue": {"$sum": "$montant"}}}
    ])
    chiffre_affaires_total = list(chiffre_affaires_total)[0]['total_revenue'] if chiffre_affaires_total else 0

    # 5. Montant total des achats (quantité * prix d'achat)
    montant_total_achats = db_achats.aggregate([
        {"$group": {"_id": None, "total_achats": {"$sum": {"$multiply": ["$quantite", "$prix"]}}}}
    ])
    montant_total_achats = list(montant_total_achats)[0]['total_achats'] if montant_total_achats else 0

    # 6. Bénéfice total (Chiffre d'affaires - Montant des achats)
    benefice_total = chiffre_affaires_total - montant_total_achats

    # Récupération des ventes et achats par mois
    ca_par_mois = list(mongo.db.ventes.aggregate([
        {
            "$group": {
                "_id": { "$dateToString": { "format": "%Y-%m", "date": "$date" }},
                "total_ventes": { "$sum": "$montant" }
            }
        },
        {"$sort": {"_id": 1}}
    ]))

    achats_par_mois = list(mongo.db.achats.aggregate([
        {
            "$group": {
                "_id": { "$dateToString": { "format": "%Y-%m", "date": "$date" }},
                "total_achats": { "$sum": "$montant" }
            }
        },
        {"$sort": {"_id": 1}}
    ]))

    # Récupération des produits les plus vendus
    produits_les_plus_vendus = list(mongo.db.ventes.aggregate([
        {
            "$group": {
                "_id": "$produit_id",
                "total_vendu": { "$sum": "$quantite_achetee" }
            }
        },
        {
            "$lookup": {
                "from": "produits",
                "localField": "_id",
                "foreignField": "_id",
                "as": "produit_info"
            }
        },
        {
            "$unwind": "$produit_info"
        },
        {
            "$project": {
                "nom": "$produit_info.nom",
                "total_vendu": 1
            }
        },
        {"$sort": {"total_vendu": -1}},
        {"$limit": 5}
    ]))

    # Récupération des produits rentables
    produits_rentables = list(mongo.db.ventes.aggregate([
        {
            "$group": {
                "_id": "$produit_id",
                "total_revenue": { "$sum": "$montant" }
            }
        },
        {
            "$lookup": {
                "from": "produits",
                "localField": "_id",
                "foreignField": "_id",
                "as": "produit_info"
            }
        },
        {
            "$unwind": "$produit_info"
        },
        {
            "$project": {
                "nom": "$produit_info.nom",
                "total_revenue": 1
            }
        },
        {"$sort": {"total_revenue": -1}},
        {"$limit": 5}
    ]))

    # Récupération du chiffre d'affaires par jour
    ca_par_jour = list(mongo.db.ventes.aggregate([
        {
            "$group": {
                "_id": { "$dateToString": { "format": "%Y-%m-%d", "date": "$date" }},
                "total_ventes": { "$sum": "$montant" }
            }
        },
        {"$sort": {"_id": 1}}
    ]))

    # Conversion des ObjectId en chaînes de caractères
    ca_par_mois = convert_objectid_to_str(ca_par_mois)
    achats_par_mois = convert_objectid_to_str(achats_par_mois)
    produits_les_plus_vendus = convert_objectid_to_str(produits_les_plus_vendus)
    produits_rentables = convert_objectid_to_str(produits_rentables)
    ca_par_jour = convert_objectid_to_str(ca_par_jour)
    return render_template('index.html', 
                           total_produits=total_produits,
                           produits_faible_quantite=produits_faible_quantite,
                           total_ventes=total_ventes,
                           chiffre_affaires_total=chiffre_affaires_total,
                           montant_total_achats=montant_total_achats,
                           benefice_total=benefice_total,
                           ca_par_mois=ca_par_mois,
                           achats_par_mois=achats_par_mois,
                           produits_les_plus_vendus=produits_les_plus_vendus,
                           produits_rentables=produits_rentables,
                           ca_par_jour=ca_par_jour)

#Alerte faible stock
@app.context_processor
def inject_low_stock_products():
    # Récupérer tous les produits ayant une quantité inférieure à 5
    low_stock_products = list(db_produits.find({"statut": "actif","quantite": {"$lt": 5}}))  # Convertir le curseur en liste
    # Compter le nombre de produits en faible quantité
    low_stock_count = len(low_stock_products)
    # Passer les produits et le nombre au template
    return dict(low_stock_products=low_stock_products, low_stock_count=low_stock_count)


# Page d'ajout utilisateurs
@app.route("/adduser", methods=["GET", "POST"])
@login_required
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role")

        # Vérification de l'existence de l'email
        existing_user = db_users.find_one({"email": email})
        if existing_user:
            return jsonify({"status": "error", "message": "Un utilisateur avec cet email existe déjà!"})

        # Vérification de la correspondance des mots de passe
        if password != confirm_password:
            return jsonify({"status": "error", "message": "Les mots de passe ne correspondent pas!"})

        # Hashage du mot de passe
        hashed_password = generate_password_hash(password)

        # Insertion dans la base de données
        db_users.insert_one({
            "nom": name,
            "email": email,
            "mot_de_passe": hashed_password,
            "role": role,
            "statut": "actif" 
        })
        return jsonify({"status": "success", "message": "Utilisateur ajouté avec succès!"})

    return render_template("adduser.html")

# Lister les utilisateurs
@app.route('/users', methods=['GET'])
@login_required
@admin_required
def show_users():
    # Récupère tous les utilisateurs actifs de la collection MongoDB
    users = list(db_users.find())
    

    # Convertir les ObjectId en chaînes de caractères
    for user in users:
        user['_id'] = str(user['_id'])
        if 'date_creation' not in user:
            user['date_creation'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('users.html', users=users)

# Modifier un utilisateur
@app.route('/edit_user/<id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    user = db_users.find_one({"_id": ObjectId(id)})

    if request.method == 'POST':
        # Lecture des données du formulaire envoyé via AJAX
        try:
            data = request.get_json()
            nom = data['nom']
            email = data['email']
            role = data['role']
            statut = data['statut']
            db_users.update_one(
                {"_id": ObjectId(id)},
                {"$set": {
                    "nom": nom,
                    "email": email,
                    "role": role,
                    "statut": statut
                }}
            )
            return jsonify({"status": "success", "message": "L'utilisateur a été modifié avec succès."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return render_template('edit_user.html', user=user)

# Archiver un utilisateur
@app.route('/archive_user/<id>', methods=['POST'])
def archive_user(id):
    db_users.update_one({"_id": ObjectId(id)}, {"$set": {"statut": "inactif"}})
    return redirect(url_for('show_users'))

#Ajout de fournisseurs
@app.route("/add_fournisseur", methods=["GET", "POST"])
@login_required
@admin_required
def add_fournisseur():
    if request.method == "POST":
        nom = request.form.get("nom")
        contact = request.form.get("contact")
        email = request.form.get("email")
        adresse = request.form.get("adresse")
        existing_fournisseur = db_fournisseurs.find_one({"email": email})
        if existing_fournisseur:
            return jsonify({"status": "error", "message": "Un fournisseur avec cet email existe déjà!"})
        if not nom or not contact or not email or not adresse:
            return jsonify({"status": "error", "message": "Tous les champs doivent être remplis."})
        db_fournisseurs.insert_one({
            "nom": nom,
            "contact": contact,
            "email": email,
            "adresse": adresse,
            "date_creation": datetime.now(),
            "statut": "actif" 
        })
        return jsonify({"status": "success", "message": "Fournisseur ajouté avec succès!"})
    return render_template("add_fournisseur.html")

#Lister les fournisseurs 
@app.route('/fournisseurs', methods=['GET'])
@login_required
@admin_required
def show_fournisseurs():
    fournisseurs = list(db_fournisseurs.find())
    for fournisseur in fournisseurs:
        fournisseur['_id'] = str(fournisseur['_id'])
        if 'date_creation' not in fournisseur:
            fournisseur['date_creation'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template('fournisseurs.html', fournisseurs=fournisseurs)

#Modification fourniseur
@app.route("/edit_fournisseur/<id>", methods=["GET"])
@login_required
@admin_required
def show_edit_fournisseur(id):
    fournisseur = db_fournisseurs.find_one({"_id": ObjectId(id)})
    return render_template("edit_fournisseur.html", fournisseur=fournisseur)
@app.route("/edit_fournisseur/<id>", methods=["POST"])
def edit_fournisseur(id):
    try:
        data = request.get_json()
        nom = data.get("nom")
        contact = data.get("contact")
        email = data.get("email")
        adresse = data.get("adresse")
        db_fournisseurs.update_one({"_id": ObjectId(id)}, {
            "$set": {
                "nom": nom,
                "contact": contact,
                "email": email,
                "adresse": adresse
            }
        })
        return jsonify({"status": "success", "message": "Le fournisseur a été modifié avec succès!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

#Archiver fournisseur
@app.route('/archive_fournisseur/<id>', methods=['POST'])
def archive_fournisseur(id):
    db_fournisseurs.update_one({"_id": ObjectId(id)}, {"$set": {"statut": "inactif"}})
    return redirect(url_for('show_fournisseurs'))

#Ajout catégorie
@app.route("/add_categorie", methods=["GET", "POST"])
@login_required
def add_categorie():
    if request.method == "POST":
        nom = request.form.get("nom")
        existing_categorie = db_categories.find_one({"nom": nom})
        if existing_categorie:
            return jsonify({"status": "error", "message": "Une catégorie avec ce nom existe déjà!"})
        if not nom:
            return jsonify({"status": "error", "message": "Le champ nom doit être rempli."})
        db_categories.insert_one({
            "nom": nom,
            "date_creation": datetime.now(),
            "statut": "actif" 
        })
        return jsonify({"status": "success", "message": "Catégorie ajoutée avec succès!"})
    return render_template("add_categorie.html")

#Liste des catégories
@app.route("/categories", methods=["GET"])
@login_required
def show_categories():
    categories = db_categories.find()
    return render_template("categories.html", categories=categories)

#Modification catégorie
@app.route("/edit_categorie/<categorie_id>", methods=["GET"])
@login_required
def get_edit_categorie(categorie_id):
    categorie = db_categories.find_one({"_id": ObjectId(categorie_id)})
    if not categorie:
        return "Catégorie non trouvée", 404
    return render_template("edit_categorie.html", categorie=categorie)

@app.route("/edit_categorie", methods=["POST"])
@login_required
def edit_categorie():
    categorie_id = request.form.get("id")
    nom = request.form.get("nom")
    if not nom:
        return jsonify({"status": "error", "message": "Le nom de la catégorie est requis."})
    result = db_categories.update_one({"_id": ObjectId(categorie_id)}, {"$set": {"nom": nom}})   
    if result.modified_count:
        return jsonify({"status": "success", "message": "Catégorie modifiée avec succès!"})  
    return jsonify({"status": "error", "message": "Aucune modification apportée."}), 400

#Archivage catégories
@app.route("/archive_categorie/<categorie_id>", methods=["POST"])
def archive_categorie(categorie_id):
    result = db_categories.update_one({"_id": ObjectId(categorie_id)}, {"$set": {"statut": "archivé"}})
    if result.modified_count:
        return jsonify({"status": "success", "message": "Catégorie archivée avec succès!"}), 200
    return jsonify({"status": "error", "message": "Échec de l'archivage de la catégorie."}), 400

#Les opérations sur les produits
@app.route("/produits")
@login_required
def show_produits():
    produits = list(db_produits.find())    
    categories = {str(category['_id']): category['nom'] for category in db_categories.find({"statut": "actif"})}
    for produit in produits:
        produit['nom_categorie'] = categories.get(str(produit['categorie_id']), "Inconnu")
    return render_template("produits.html", produits=produits)

@app.route("/add_produit", methods=["GET", "POST"])
@login_required
def add_produit():
    if request.method == "POST":
        nom = request.form.get("nom")
        prix = request.form.get("prix")
        quantite = request.form.get("quantite")
        categorie_id = request.form.get("categorie")
        if not nom or not prix or not quantite or not categorie_id:
            return jsonify({"status": "error", "message": "Tous les champs doivent être remplis."})
        db_produits.insert_one({
            "nom": nom,
            "prix": float(prix),
            "quantite": int(quantite),
            "categorie_id": categorie_id,
            "date_creation": datetime.now(),
            "statut": "actif"
        })
        return jsonify({"status": "success", "message": "Produit ajouté avec succès!"})
    categories = db_categories.find({"statut": "actif"})
    return render_template("add_produit.html", categories=categories)

@app.route("/edit_produit", methods=["GET", "POST"])
@login_required
def edit_produit():
    produit_id = request.args.get('id')
    if request.method == "POST":
        nom = request.form.get("nom")
        prix = request.form.get("prix")
        quantite = request.form.get("quantite")
        categorie_id = request.form.get("categorie")
        db_produits.update_one({"_id": ObjectId(produit_id)}, {
            "$set": {
                "nom": nom,
                "prix": float(prix),
                "quantite": int(quantite),
                "categorie_id": categorie_id
            }
        })
        return jsonify({"status": "success", "message": "Produit modifié avec succès!"})

    produit = db_produits.find_one({"_id": ObjectId(produit_id)})
    categories = db_categories.find({"statut": "actif"})
    return render_template("edit_produit.html", produit=produit, categories=categories)

@app.route("/archive_produit/<id>", methods=["POST"])
def archive_produit(id):
    db_produits.update_one({"_id": ObjectId(id)}, {"$set": {"statut": "archivé"}})
    return jsonify({"status": "success", "message": "Produit archivé avec succès!"})

# Opération d'entrée/sortie
@app.route("/operation", methods=["GET"])
@login_required
def operation():
    produits = db_produits.find({"statut": "actif"})
    fournisseurs = db_fournisseurs.find({"statut": "actif"})
    return render_template("operation.html", produits=produits, fournisseurs=fournisseurs)

@app.route("/add_operation", methods=["POST"])
@login_required
def add_operation():
    type_operation = request.form.get("typeOperation")
    produit_id = request.form.get("produit_id")
    quantite = int(request.form.get("quantite"))    
    date_aujourdhui = datetime.now()
    operateur = session.get("user_name")    
    if type_operation == "vente":
        produit = db_produits.find_one({"_id": ObjectId(produit_id)})
        montant = quantite * produit["prix"]
        db_ventes.insert_one({
            "produit_id": ObjectId(produit_id),
            "quantite_achetee": quantite,
            "montant": montant,
            "date": date_aujourdhui,
            "operateur": operateur
        })
        db_produits.update_one({"_id": ObjectId(produit_id)}, {"$inc": {"quantite": -quantite}})
    elif type_operation == "achat":
        produit = db_produits.find_one({"_id": ObjectId(produit_id)})
        prix = float(request.form['prix'])
        fournisseur_id = request.form.get("fournisseur_id")
        montant = quantite * prix
        db_achats.insert_one({
            "produit_id": ObjectId(produit_id),
            "quantite": quantite,
            "prix": prix,
            "montant": montant,
            "fournisseur_id": ObjectId(fournisseur_id),
            "date": date_aujourdhui,
            "operateur": operateur
        })
        db_produits.update_one({"_id": ObjectId(produit_id)}, {"$inc": {"quantite": quantite}})
    return jsonify({"status": "success", "message": "Opération enregistrée avec succès!"})

# Liste des achats 
@app.route("/achats", methods=['GET'])
@login_required
def liste_achats():
    achats = list(db_achats.find())    
    for achat in achats:
        produit = db_produits.find_one({"_id": achat['produit_id']})
        fournisseur = db_fournisseurs.find_one({"_id": achat['fournisseur_id']})
        achat['produit_nom'] = produit['nom'] if produit else "Inconnu"
        achat['fournisseur_nom'] = fournisseur['nom'] if fournisseur else "Inconnu"
        achat['date_achat'] = achat.get('date')     
    return render_template("liste_achats.html", achats=achats)

#Modification achat
@app.route("/edit_achat/<id>", methods=["GET", "POST"])
@login_required
def edit_achat(id):
    achat = db_achats.find_one({"_id": ObjectId(id)})    
    if request.method == "POST":
        produit_id = request.form.get("produit_id")
        quantite = int(request.form.get("quantite"))
        prix = float(request.form.get("prix"))
        fournisseur_id = request.form.get("fournisseur_id")
        montant = quantite * prix
        previous_quantity = achat['quantite'] 
        db_achats.update_one(
            {"_id": ObjectId(id)},
            {"$set": {
                "produit_id": ObjectId(produit_id),
                "quantite": quantite,
                "prix" : prix,
                "montant" : montant,
                "fournisseur_id": ObjectId(fournisseur_id),
                "date": datetime.now(),
            }}
        )       
        if quantite > previous_quantity:
            difference = quantite - previous_quantity
            db_produits.update_one(
                {"_id": ObjectId(produit_id)},
                {"$inc": {"quantite": difference}}
            )
        else:
            difference = previous_quantity - quantite
            db_produits.update_one(
                {"_id": ObjectId(produit_id)},
                {"$inc": {"quantite": -difference}}
            )

        return jsonify({"status": "success", "message": "Achat modifié avec succès!"})
    return render_template("edit_achat.html", achat=achat, produits=db_produits.find(), fournisseurs=db_fournisseurs.find())

# Liste des ventes
@app.route("/ventes", methods=['GET'])
@login_required
def liste_ventes():
    ventes = list(db_ventes.find()) 
    for vente in ventes:
        produit = db_produits.find_one({"_id": vente['produit_id']})
        vente['produit_nom'] = produit['nom'] if produit else "Inconnu"
        vente['prix'] = produit['prix'] if produit else 0
        vente['montant'] = vente['quantite_achetee'] * vente['prix']
        vente['date_vente'] = vente.get('date')        
    return render_template("liste_ventes.html", ventes=ventes)

# Modification vente
@app.route("/edit_vente/<id>", methods=["GET", "POST"])
@login_required
def edit_vente(id):
    vente = db_ventes.find_one({"_id": ObjectId(id)})   
    if request.method == "POST":
        produit_id = request.form.get("produit_id")
        quantite = int(request.form.get("quantite_achetee"))
        produit = db_produits.find_one({"_id": ObjectId(produit_id)})
        prix = produit['prix'] if produit else 0
        montant = quantite * prix
        previous_quantity = vente['quantite_achetee']         
        db_ventes.update_one(
            {"_id": ObjectId(id)},
            {"$set": {
                "produit_id": ObjectId(produit_id),
                "quantite_achetee": quantite,
                "prix" : prix,
                "montant" : montant,
                "date": datetime.now(),
            }}
        )        
        if quantite > previous_quantity:
            difference = quantite - previous_quantity
            db_produits.update_one(
                {"_id": ObjectId(produit_id)},
                {"$inc": {"quantite": -difference}}
            )
        else:
            difference = previous_quantity - quantite
            db_produits.update_one(
                {"_id": ObjectId(produit_id)},
                {"$inc": {"quantite": difference}}
            )
        return jsonify({"status": "success", "message": "Vente modifiée avec succès!"})
    return render_template("edit_vente.html", vente=vente, produits=db_produits.find())

#Rapport mensuel PDF
# La fonction de création de rapport PDF
def create_pdf_report(produits_data, total_ca, total_depenses, total_benefice, mois):
    pdf_buffer = BytesIO()
    with PdfPages(pdf_buffer) as pdf:
        fig, ax = plt.subplots(figsize=(8, 7))
        title = f"Sama Stock | Rapport du mois de {mois}"
        plt.text(0.5, 0.90, title, ha='center', va='center', fontsize=16, weight='bold', transform=fig.transFigure)
        plt.subplots_adjust(top=0.95)
        table_data = [["Nom du Produit", "Quantité en Stock", "Quantité Vendue", "Chiffre d'Affaires (F CFA)"]] + produits_data
        ax.axis('off')
        ax.axis('tight')
        produit_table = ax.table(cellText=table_data, cellLoc='center', loc='center', colColours=["#f0f0f0"]*4)
        produit_table.auto_set_font_size(False)
        produit_table.set_fontsize(10)
        produit_table.scale(1.2, 1.2)
        produit_table.auto_set_column_width(col=list(range(len(table_data[0]))))
        produit_table_pos = 0.4
        summary_data = [
            ["Total Chiffre d'Affaires (F CFA)", total_ca],
            ["Total Dépenses (F CFA)", total_depenses],
            ["Bénéfice (F CFA)", total_benefice]
        ]
        summary_table = ax.table(cellText=summary_data, cellLoc='center', colColours=["#f7f7f7"]*2, loc='bottom', bbox=[0.15, 0.1, 0.7, 0.15])  # Ajustement de la position du tableau de résumé
        summary_table.auto_set_font_size(False)
        summary_table.set_fontsize(10)
        pdf.savefig(fig, bbox_inches='tight')

    pdf_buffer.seek(0)
    return send_file(pdf_buffer, as_attachment=False, download_name="rapport_mensuel_sama_stock.pdf", mimetype='application/pdf')

# Route Flask pour générer et visualiser le rapport mensuel
@app.route('/rapport_mensuel')
@login_required
def generate_report():
    now = datetime.now()
    current_month = now.month
    current_year = now.year
    month_name = now.strftime("%B")
    ventes_mensuelles = list(db_ventes.aggregate([
        {"$match": {"date": {"$gte": datetime(current_year, current_month, 1), "$lt": datetime(current_year, current_month + 1, 1)}}},
        {"$group": {"_id": "$produit_id", "quantite_achetee": {"$sum": "$quantite_achetee"}, "chiffre_affaires": {"$sum": "$montant"}}}
    ]))
    produits = list(db_produits.find())
    ventes_dict = {str(vente['_id']): vente for vente in ventes_mensuelles}
    produits_data = []
    total_ca = 0
    for produit in produits:
        produit_id = str(produit['_id'])
        quantite_achetee = ventes_dict[produit_id]['quantite_achetee'] if produit_id in ventes_dict else 0
        ca_produit = ventes_dict[produit_id]['chiffre_affaires'] if produit_id in ventes_dict else 0
        total_ca += ca_produit

        produits_data.append([
            produit['nom'],
            produit['quantite'],
            quantite_achetee,
            ca_produit
        ])
    total_achats = list(db_achats.aggregate([
        {"$match": {"date": {"$gte": datetime(current_year, current_month, 1), "$lt": datetime(current_year, current_month + 1, 1)}}},
        {"$group": {"_id": None, "total_achats": {"$sum": "$montant"}}}
    ]))

    total_depenses = total_achats[0]['total_achats'] if total_achats else 0
    total_benefice = total_ca - total_depenses
    return create_pdf_report(produits_data, total_ca, total_depenses, total_benefice, month_name)

# =================== Démarrage de l'application =====================

if __name__ == '__main__':
    app.run(debug=True)
