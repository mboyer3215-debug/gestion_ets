#!/usr/bin/env python3
"""
Application de gestion d'entreprise de prestations de services
Accessible sur PC, téléphone et tablette
"""

print("=" * 80)
print(">>> FICHIER APP.PY VERSION AVEC RAPPELS PERSONNALISÉS <<<")
print(">>> SI VOUS VOYEZ CE MESSAGE AU DÉMARRAGE, C'EST LE BON FICHIER <<<")
print("=" * 80)

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import json
import shutil
import sys

import subprocess
import requests
import pytz
from pathlib import Path

# Imports pour Google Calendar
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False
    print("⚠️ Modules Google Calendar non installés. Installez avec: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

SCOPES = ['https://www.googleapis.com/auth/calendar']

# ============================================================================
# STRUCTURE HIÉRARCHIQUE DES PRESTATIONS (Thème → Domaine → Type)
# ============================================================================

PRESTATIONS_STRUCTURE = {
    'Formation': {
        'Secourisme': ['FI SST', 'MAC SST', 'Gestes de Premiers Secours'],
        'Incendie': ['EPI', 'Extincteur', 'Evacuation', 'SSIAP 1', 'SSIAP 2', 'SSIAP 3'],
        'Prévention': ['Gestes et Postures']
    },
    'Service': {
        'Prévention ERP': ['Dossier sécurité', 'Notice de sécurité', 'Notice accessibilité']
    },
    'Audit': {
        'Risque professionnel': ['DUERP'],
        'Risque incendie': ['RCCI']
    }
}

# Déterminer le répertoire de base
if getattr(sys, 'frozen', False):
    # Mode exécutable
    base_path = os.path.dirname(sys.executable)
else:
    # Mode développement
    base_path = os.path.dirname(os.path.abspath(__file__))

# Configuration de l'application avec chemins explicites
app = Flask(__name__, 
            template_folder=os.path.join(base_path, 'templates'),
            static_folder=os.path.join(base_path, 'static'))
app.config['SECRET_KEY'] = 'votre-cle-secrete-a-changer'

# Détection du chemin de la base de données selon le mode d'exécution
if getattr(sys, 'frozen', False):
    # Mode exécutable PyInstaller
    base_dir = os.path.dirname(sys.executable)
    instance_dir = os.path.join(base_dir, 'instance')
    db_path = os.path.join(instance_dir, 'gestion_entreprise.db')

    # Créer le dossier instance s'il n'existe pas
    os.makedirs(instance_dir, exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f">> Mode executable: Base de donnees = {db_path}")
    print(f">> Verification base de donnees: {'EXISTE' if os.path.exists(db_path) else 'INEXISTANTE'}")
else:
    # Mode développement Python normal
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gestion_entreprise.db'
    print(">> Mode developpement: Base de donnees = sqlite:///gestion_entreprise.db")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'

# Créer le dossier uploads s'il n'existe pas
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuration des sauvegardes
app.config['BACKUP_FOLDER'] = 'Sauvegardes'
app.config['GDRIVE_BACKUP_PATH'] = r'G:\Mon Drive\Sauvegardes App'
os.makedirs(app.config['BACKUP_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# ============================================================================
# MODÈLES DE BASE DE DONNÉES
# ============================================================================
class Utilisateur(db.Model):
    """Table des utilisateurs pour l'authentification"""
    __tablename__ = 'utilisateurs'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nom = db.Column(db.String(100))
    email = db.Column(db.String(120))
    role = db.Column(db.String(20), default='admin')
    actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_connexion = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
class Client(db.Model):
    """Table des clients"""
    __tablename__ = 'clients'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100))
    entreprise = db.Column(db.String(200))
    email = db.Column(db.String(120))
    telephone = db.Column(db.String(20))
    adresse = db.Column(db.Text)
    code_postal = db.Column(db.String(10))
    ville = db.Column(db.String(100))
    notes = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)
    delai_paiement_jours = db.Column(db.Integer, default=30)  # Délai de paiement en jours
    calendrier_google = db.Column(db.String(500))  # ID du calendrier Google dédié à ce client
    statut_client = db.Column(db.String(50), default='Client')  # 'Prospect' ou 'Client'
    date_conversion = db.Column(db.DateTime)  # Date de conversion d'un prospect en client

    # Relations
    prestations = db.relationship('Prestation', backref='client', lazy=True, cascade='all, delete-orphan')
    contacts = db.relationship('Contact', backref='client', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'prenom': self.prenom,
            'entreprise': self.entreprise,
            'email': self.email,
            'telephone': self.telephone,
            'adresse': self.adresse,
            'code_postal': self.code_postal,
            'ville': self.ville,
            'notes': self.notes,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'actif': self.actif
        }

class Contact(db.Model):
    """Table des contacts liés aux clients"""
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)

    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100))
    poste = db.Column(db.String(100))  # Fonction dans l'entreprise
    tel_fixe = db.Column(db.String(20))
    tel_portable = db.Column(db.String(20))
    email = db.Column(db.String(120))
    notes = db.Column(db.Text)

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'client_id': self.client_id,
            'nom': self.nom,
            'prenom': self.prenom,
            'poste': self.poste,
            'tel_fixe': self.tel_fixe,
            'tel_portable': self.tel_portable,
            'email': self.email,
            'notes': self.notes,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'actif': self.actif
        }

class Prestation(db.Model):
    """Table des prestations (formations, services)"""
    __tablename__ = 'prestations'

    id = db.Column(db.Integer, primary_key=True)

    # Client et demande
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    demandeur = db.Column(db.String(200))  # Nom du demandeur si différent du client
    date_demande = db.Column(db.Date)  # Date de la demande
    reference_commande = db.Column(db.String(100))  # Référence de la commande

    # Type et thème (hiérarchie: Thème → Domaine → Type)
    theme_prestation = db.Column(db.String(50), nullable=False)  # Thème/Famille (Formation, Service, Audit)
    domaine_prestation = db.Column(db.String(100))  # Domaine (ex: Secourisme, Incendie, Prévention)
    type_prestation = db.Column(db.String(100))  # Type précis (ex: FI SST, MAC SST, DUERP)
    titre = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Dates et horaires
    date_debut = db.Column(db.DateTime, nullable=False)
    date_fin = db.Column(db.DateTime)
    duree_heures = db.Column(db.Float)
    creneau = db.Column(db.String(20))  # "Matin", "Après-midi", "Journée", "Personnalisé"
    journee_entiere = db.Column(db.Boolean, default=False)  # Si la prestation dure toute la journée

    # Lieu
    lieu = db.Column(db.String(200))
    adresse_prestation = db.Column(db.Text)
    code_postal_prestation = db.Column(db.String(10))
    ville_prestation = db.Column(db.String(100))
    distance_km = db.Column(db.Float)
    duree_trajet_minutes = db.Column(db.Integer)  # Durée du trajet en minutes

    # Participants et logistique
    nb_stagiaires = db.Column(db.Integer)  # Nombre de stagiaires
    nb_repas = db.Column(db.Integer)  # Nombre de repas
    nb_hebergements = db.Column(db.Integer)  # Nombre d'hébergements

    # Financier (gardés pour compatibilité, mais plus dans le formulaire)
    tarif_horaire = db.Column(db.Float)
    tarif_total = db.Column(db.Float)
    frais_fournitures = db.Column(db.Float)  # Frais de fournitures
    frais_deplacement = db.Column(db.Float)  # Frais de déplacement
    statut_paiement = db.Column(db.String(50))  # En attente, Payé, Partiel, En retard
    statut_facture = db.Column(db.String(50))  # Non envoyée, Envoyée, Payée, En retard
    statut_devis = db.Column(db.String(50))  # Non envoyé, Envoyé, Accepté, Refusé

    # Statut
    statut = db.Column(db.String(50), default='Planifiée')  # Planifiée, En cours, Terminée, Annulée

    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    commentaires = db.Column(db.Text)  # Remplace 'notes'
    notes = db.Column(db.Text)  # Gardé pour compatibilité

    # Gestion des tâches
    titre_tache = db.Column(db.String(200))
    description_tache = db.Column(db.Text)
    date_debut_tache = db.Column(db.DateTime)
    date_echeance_tache = db.Column(db.DateTime)
    priorite_tache = db.Column(db.String(50), default='Moyenne')  # Basse, Moyenne, Haute
    statut_tache = db.Column(db.String(50), default='À faire')  # À faire, En cours, Terminée

    # Synchronisation Google Calendar
    gcal_event_id = db.Column(db.String(500))  # ID de l'événement Google Calendar
    gcal_synced = db.Column(db.Boolean, default=False)  # Si la prestation est synchronisée
    gcal_last_sync = db.Column(db.DateTime)  # Date de dernière synchronisation
    calendrier_id = db.Column(db.String(500))  # ID du calendrier Google dédié à cette prestation

    # Relations
    documents = db.relationship('Document', backref='prestation', lazy=True, cascade='all, delete-orphan')
    gcal_blocages = db.relationship('GcalBlocage', backref='prestation', lazy=True, cascade='all, delete-orphan')
    sessions = db.relationship('SessionPrestation', backref='prestation', lazy=True, cascade='all, delete-orphan', order_by='SessionPrestation.ordre')
    lignes_tarif_deplacement = db.relationship('LignePrestationDeplacement', backref='prestation', lazy=True, cascade='all, delete-orphan')
    lignes_tarif_fourniture = db.relationship('LignePrestationFourniture', backref='prestation', lazy=True, cascade='all, delete-orphan')
    lignes_tarif_prestation = db.relationship('LignePrestationTarif', backref='prestation', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'type_prestation': self.type_prestation,
            'titre': self.titre,
            'description': self.description,
            'client_id': self.client_id,
            'client_nom': f"{self.client.prenom or ''} {self.client.nom}" if self.client else '',
            'date_debut': self.date_debut.isoformat() if self.date_debut else None,
            'date_fin': self.date_fin.isoformat() if self.date_fin else None,
            'duree_heures': self.duree_heures,
            'lieu': self.lieu,
            'adresse_prestation': self.adresse_prestation,
            'distance_km': self.distance_km,
            'tarif_horaire': self.tarif_horaire,
            'tarif_total': self.tarif_total,
            'statut_paiement': self.statut_paiement,
            'statut': self.statut,
            'notes': self.notes
        }

class Document(db.Model):
    """Table des documents liés aux prestations"""
    __tablename__ = 'documents'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    nom_fichier = db.Column(db.String(200), nullable=False)
    nom_original = db.Column(db.String(200), nullable=False)
    type_document = db.Column(db.String(50))  # Contrat, Support, Facture, Autre
    chemin_fichier = db.Column(db.String(500), nullable=False)
    taille_octets = db.Column(db.Integer)

    date_upload = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    def to_dict(self):
        return {
            'id': self.id,
            'prestation_id': self.prestation_id,
            'nom_fichier': self.nom_fichier,
            'nom_original': self.nom_original,
            'type_document': self.type_document,
            'taille_octets': self.taille_octets,
            'date_upload': self.date_upload.isoformat() if self.date_upload else None,
            'notes': self.notes
        }

class CalendrierConfig(db.Model):
    """Configuration des calendriers Google"""
    __tablename__ = 'calendrier_config'

    id = db.Column(db.Integer, primary_key=True)
    config_json = db.Column(db.Text)  # Stockage de la config des calendriers
    derniere_synchro = db.Column(db.DateTime)

class GcalBlocage(db.Model):
    """Événements de blocage Google Calendar associés aux prestations"""
    __tablename__ = 'gcal_blocages'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)
    calendar_id = db.Column(db.String(500), nullable=False)  # ID du calendrier Google
    event_id = db.Column(db.String(500), nullable=False)  # ID de l'événement Google Calendar
    calendar_name = db.Column(db.String(200))  # Nom du calendrier pour référence
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

class SessionPrestation(db.Model):
    """Sessions/dates multiples pour une prestation (formations sur dates non consécutives)"""
    __tablename__ = 'sessions_prestation'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    # Dates de cette session
    date_debut = db.Column(db.DateTime, nullable=False)
    date_fin = db.Column(db.DateTime)
    duree_heures = db.Column(db.Float)
    journee_complete = db.Column(db.Boolean, default=False)  # Si coché, implique journée entière dans Google Calendar

    # Synchronisation Google Calendar (un événement par session)
    gcal_event_id = db.Column(db.String(500))  # ID de l'événement Google Calendar pour cette session
    gcal_synced = db.Column(db.Boolean, default=False)

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    ordre = db.Column(db.Integer, default=0)  # Pour trier les sessions

class Indisponibilite(db.Model):
    """Périodes d'indisponibilité (vacances, maladie, etc.) bloquant tous les calendriers"""
    __tablename__ = 'indisponibilites'

    id = db.Column(db.Integer, primary_key=True)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    motif = db.Column(db.String(100), nullable=False)  # Vacances, Maladie, Formation, Congé, Autre
    note = db.Column(db.Text)  # Note optionnelle

    # IDs des événements créés sur chaque calendrier (format JSON)
    # {"calendar_id_1": "event_id_1", "calendar_id_2": "event_id_2", ...}
    gcal_events = db.Column(db.Text)  # JSON

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

class Sauvegarde(db.Model):
    """Historique des sauvegardes"""
    __tablename__ = 'sauvegardes'

    id = db.Column(db.Integer, primary_key=True)
    date_sauvegarde = db.Column(db.DateTime, default=datetime.utcnow)
    nom_fichier = db.Column(db.String(200), nullable=False)
    taille_octets = db.Column(db.Integer)
    chemin_local = db.Column(db.String(500))
    chemin_gdrive = db.Column(db.String(500))
    statut_gdrive = db.Column(db.String(50))  # Success, Failed, N/A
    notes = db.Column(db.Text)

class Entreprise(db.Model):
    """Informations de l'entreprise"""
    __tablename__ = 'entreprise'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    siret = db.Column(db.String(50))
    adresse = db.Column(db.Text, nullable=False)
    code_postal = db.Column(db.String(10))
    ville = db.Column(db.String(100))
    telephone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    site_web = db.Column(db.String(200))
    logo = db.Column(db.String(500))  # Chemin vers le logo
    notes = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Configuration notifications
    notif_actives = db.Column(db.Boolean, default=False)
    # Email
    email_smtp_host = db.Column(db.String(200))
    email_smtp_port = db.Column(db.Integer, default=587)
    email_smtp_user = db.Column(db.String(200))
    email_smtp_password = db.Column(db.String(200))
    # SMS (optionnel - plusieurs services possibles)
    sms_actif = db.Column(db.Boolean, default=False)
    sms_service = db.Column(db.String(50))  # 'twilio', 'smsmode', etc.
    sms_api_key = db.Column(db.String(200))
    sms_api_secret = db.Column(db.String(200))
    sms_from_number = db.Column(db.String(20))

    # Informations juridiques et bancaires
    statut_juridique = db.Column(db.String(100))  # SARL, SAS, EURL, Entreprise individuelle, etc.
    capital = db.Column(db.Float)
    numero_nda = db.Column(db.String(50))  # Numéro de déclaration d'activité (formation)
    rcs = db.Column(db.String(100))  # Registre du Commerce et des Sociétés
    domiciliation_bancaire = db.Column(db.String(200))
    iban = db.Column(db.String(34))
    bic = db.Column(db.String(11))

class Notification(db.Model):
    """Historique des notifications envoyées"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    type_notif = db.Column(db.String(50), nullable=False)  # rappel_prestation, facture_non_envoyee, facture_non_payee
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'))
    destinataire_nom = db.Column(db.String(200))
    destinataire_email = db.Column(db.String(200))
    destinataire_tel = db.Column(db.String(20))
    canal = db.Column(db.String(20))  # 'email', 'sms'
    statut = db.Column(db.String(50), default='pending')  # pending, sent, failed
    date_programmee = db.Column(db.DateTime)
    date_envoi = db.Column(db.DateTime)
    erreur_message = db.Column(db.Text)
    contenu = db.Column(db.Text)

    # Relation
    prestation = db.relationship('Prestation', backref=db.backref('notifications', cascade='all, delete-orphan'))

class Facture(db.Model):
    """Table des factures"""
    __tablename__ = 'factures'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    # Références
    reference_facture = db.Column(db.String(100), unique=True, nullable=False)  # FA-27.2020-12-039
    date_facture = db.Column(db.Date, nullable=False)
    date_envoi = db.Column(db.Date)

    # Références paiement
    reference_paiement = db.Column(db.String(100))
    date_paiement = db.Column(db.Date)
    mail_envoi = db.Column(db.String(200))  # Email destinataire

    # Calcul des prix (stockés pour historique)
    deplacement_prix_ht = db.Column(db.Float, default=0)
    fourniture_prix_ht = db.Column(db.Float, default=0)
    prestation_prix_ht = db.Column(db.Float, default=0)
    acompte_prix_ht = db.Column(db.Float, default=0)
    remise = db.Column(db.Float, default=0)  # En pourcentage ou montant
    majoration = db.Column(db.Float, default=0)
    remise_ht = db.Column(db.Float, default=0)
    total_prix_ht = db.Column(db.Float)
    tva_applicable = db.Column(db.Float, default=0)  # En pourcentage
    total_ttc = db.Column(db.Float)

    # Commentaire
    commentaire = db.Column(db.Text)

    # Rib
    rib = db.Column(db.String(200))

    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    prestation = db.relationship('Prestation', backref=db.backref('factures', cascade='all, delete-orphan'))
    lignes_deplacement = db.relationship('LigneFactureDeplacement', backref='facture', lazy=True, cascade='all, delete-orphan')
    lignes_fourniture = db.relationship('LigneFactureFourniture', backref='facture', lazy=True, cascade='all, delete-orphan')
    lignes_prestation = db.relationship('LigneFacturePrestation', backref='facture', lazy=True, cascade='all, delete-orphan')

class LigneFactureDeplacement(db.Model):
    """Lignes de frais de déplacement dans une facture"""
    __tablename__ = 'lignes_facture_deplacement'

    id = db.Column(db.Integer, primary_key=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id'), nullable=False)

    code = db.Column(db.String(50))  # REP, KM
    type = db.Column(db.String(100))  # REPAS, PROXIMITE
    nbre = db.Column(db.Float, default=0)  # Nombre ou quantité
    pu_ht = db.Column(db.Float, default=0)  # Prix unitaire HT
    pt_ht = db.Column(db.Float, default=0)  # Prix total HT

class LigneFactureFourniture(db.Model):
    """Lignes de frais de fourniture dans une facture"""
    __tablename__ = 'lignes_facture_fourniture'

    id = db.Column(db.Integer, primary_key=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id'), nullable=False)

    code = db.Column(db.String(50))  # INCENDIE
    type = db.Column(db.String(100))  # EXTINCTEUR_EAU, EXTINCTEUR_CO2
    nbre = db.Column(db.Float, default=0)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

class LigneFacturePrestation(db.Model):
    """Lignes de tarif prestation dans une facture"""
    __tablename__ = 'lignes_facture_prestation'

    id = db.Column(db.Integer, primary_key=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id'), nullable=False)

    code = db.Column(db.String(50))  # INCENDIE
    type = db.Column(db.String(100))  # EPI
    nbre = db.Column(db.Float, default=1)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

class Paiement(db.Model):
    """Table des paiements"""
    __tablename__ = 'paiements'

    id = db.Column(db.Integer, primary_key=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id'), nullable=False)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    # Numérotation
    numero_paiement = db.Column(db.String(100), unique=True)  # P-001, P-002, etc.
    numero_facture = db.Column(db.String(100))  # Référence de la facture

    # Dates
    date_butoir = db.Column(db.Date)  # Date limite de paiement (date_facture + délai client)
    date_paiement = db.Column(db.Date)  # Date réelle du paiement

    # Montants
    montant_total = db.Column(db.Float)  # Montant total à payer
    montant_paye = db.Column(db.Float, default=0)  # Montant déjà payé

    # Mode de paiement
    mode_paiement = db.Column(db.String(50))  # Virement, Chèque, Espèces, CB, etc.

    # Calculs automatiques
    nb_jours_retard = db.Column(db.Integer, default=0)  # Calculé automatiquement
    nb_relances = db.Column(db.Integer, default=0)  # Nombre de relances envoyées

    # Statut
    statut = db.Column(db.String(50), default='En attente')  # En attente, Partiel, Payé, En retard

    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    # Relations
    facture = db.relationship('Facture', backref=db.backref('paiements', cascade='all, delete-orphan'))
    prestation = db.relationship('Prestation', backref=db.backref('paiements', cascade='all, delete-orphan'))

class Devis(db.Model):
    """Table des devis"""
    __tablename__ = 'devis'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    # Références
    reference_devis = db.Column(db.String(100), unique=True, nullable=False)
    date_devis = db.Column(db.Date, nullable=False)
    date_envoi = db.Column(db.Date)
    date_validite = db.Column(db.Date)  # Date de validité du devis

    # Mail
    mail_envoi = db.Column(db.String(200))

    # Calcul des prix (similaire à facture)
    deplacement_prix_ht = db.Column(db.Float, default=0)
    fourniture_prix_ht = db.Column(db.Float, default=0)
    prestation_prix_ht = db.Column(db.Float, default=0)
    remise = db.Column(db.Float, default=0)
    remise_ht = db.Column(db.Float, default=0)
    total_prix_ht = db.Column(db.Float)
    tva_applicable = db.Column(db.Float, default=0)
    total_ttc = db.Column(db.Float)

    # Commentaire
    commentaire = db.Column(db.Text)

    # Statut
    statut = db.Column(db.String(50), default='Non envoyé')  # Non envoyé, Envoyé, En attente, Accepté, Refusé

    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    prestation = db.relationship('Prestation', backref=db.backref('devis_list', cascade='all, delete-orphan'))
    lignes_deplacement = db.relationship('LigneDevisDeplacement', backref='devis', lazy=True, cascade='all, delete-orphan')
    lignes_fourniture = db.relationship('LigneDevisFourniture', backref='devis', lazy=True, cascade='all, delete-orphan')
    lignes_prestation = db.relationship('LigneDevisPrestation', backref='devis', lazy=True, cascade='all, delete-orphan')

class LigneDevisDeplacement(db.Model):
    """Lignes de frais de déplacement dans un devis"""
    __tablename__ = 'lignes_devis_deplacement'

    id = db.Column(db.Integer, primary_key=True)
    devis_id = db.Column(db.Integer, db.ForeignKey('devis.id'), nullable=False)

    code = db.Column(db.String(50))
    type = db.Column(db.String(100))
    nbre = db.Column(db.Float, default=0)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

class LigneDevisFourniture(db.Model):
    """Lignes de frais de fourniture dans un devis"""
    __tablename__ = 'lignes_devis_fourniture'

    id = db.Column(db.Integer, primary_key=True)
    devis_id = db.Column(db.Integer, db.ForeignKey('devis.id'), nullable=False)

    code = db.Column(db.String(50))
    type = db.Column(db.String(100))
    nbre = db.Column(db.Float, default=0)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

class LigneDevisPrestation(db.Model):
    """Lignes de tarif prestation dans un devis"""
    __tablename__ = 'lignes_devis_prestation'

    id = db.Column(db.Integer, primary_key=True)
    devis_id = db.Column(db.Integer, db.ForeignKey('devis.id'), nullable=False)

    code = db.Column(db.String(50))
    type = db.Column(db.String(100))
    nbre = db.Column(db.Float, default=1)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

# ============================================================================
# LIGNES DE TARIF DE PRESTATION (sauvegardées au niveau de la prestation)
# ============================================================================

class LignePrestationDeplacement(db.Model):
    """Lignes de frais de déplacement au niveau de la prestation"""
    __tablename__ = 'lignes_prestation_deplacement'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    code = db.Column(db.String(50))  # REP, KM
    type = db.Column(db.String(100))  # REPAS, PROXIMITE
    nbre = db.Column(db.Float, default=0)  # Nombre ou quantité
    pu_ht = db.Column(db.Float, default=0)  # Prix unitaire HT
    pt_ht = db.Column(db.Float, default=0)  # Prix total HT

class LignePrestationFourniture(db.Model):
    """Lignes de frais de fourniture au niveau de la prestation"""
    __tablename__ = 'lignes_prestation_fourniture'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    code = db.Column(db.String(50))  # INCENDIE
    type = db.Column(db.String(100))  # EXTINCTEUR_EAU, EXTINCTEUR_CO2
    nbre = db.Column(db.Float, default=0)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

class LignePrestationTarif(db.Model):
    """Lignes de tarif prestation au niveau de la prestation"""
    __tablename__ = 'lignes_prestation_tarif'

    id = db.Column(db.Integer, primary_key=True)
    prestation_id = db.Column(db.Integer, db.ForeignKey('prestations.id'), nullable=False)

    code = db.Column(db.String(50))  # INCENDIE, FORMATION
    type = db.Column(db.String(100))  # EPI, SST
    nbre = db.Column(db.Float, default=1)
    pu_ht = db.Column(db.Float, default=0)
    pt_ht = db.Column(db.Float, default=0)

# ============================================================================
# CONTEXT PROCESSOR - Variables globales pour tous les templates
# ============================================================================

@app.context_processor
def inject_global_vars():
    """Injecter des variables globales dans tous les templates"""

    # Compter les factures en retard (factures dont le délai de paiement est dépassé)
    factures_retard = 0
    try:
        factures = Facture.query.all()
        for facture in factures:
            # Vérifier si un paiement existe et est payé
            paiements_complets = Paiement.query.filter_by(
                facture_id=facture.id,
                statut='Payé'
            ).first()

            if not paiements_complets:
                # Calculer la date butoir
                if facture.date_facture and facture.prestation and facture.prestation.client:
                    delai = facture.prestation.client.delai_paiement_jours or 30
                    date_butoir = facture.date_facture + timedelta(days=delai)

                    # Si aujourd'hui > date butoir, c'est en retard
                    if datetime.now().date() > date_butoir:
                        factures_retard += 1
    except:
        pass

    # Compter les paiements en retard (paiements dont la date butoir est dépassée)
    paiements_retard = 0
    try:
        paiements = Paiement.query.filter(Paiement.statut.in_(['En attente', 'Partiel'])).all()
        for paiement in paiements:
            if paiement.date_butoir and datetime.now().date() > paiement.date_butoir:
                paiements_retard += 1
    except:
        pass

    # Compter les factures en cours (factures envoyées mais non payées)
    factures_en_cours = 0
    try:
        factures = Facture.query.filter(Facture.date_envoi.isnot(None)).all()
        for facture in factures:
            # Vérifier si un paiement existe et est payé
            paiements_complets = Paiement.query.filter_by(
                facture_id=facture.id,
                statut='Payé'
            ).first()

            if not paiements_complets:
                factures_en_cours += 1
    except:
        pass

    # Info sauvegarde
    derniere_sauv = Sauvegarde.query.order_by(Sauvegarde.date_sauvegarde.desc()).first()
    jours_backup = 999
    if derniere_sauv:
        delta = datetime.now() - derniere_sauv.date_sauvegarde
        jours_backup = delta.days

    # Tâches urgentes : prestations avec tâches non terminées et échéance proche
    taches_urgentes = []
    try:
        aujourd_hui = datetime.now()
        dans_7_jours = aujourd_hui + timedelta(days=7)

        # Récupérer les prestations avec tâches non terminées
        prestations_taches = Prestation.query.filter(
            Prestation.titre_tache.isnot(None),
            Prestation.statut_tache.in_(['À faire', 'En cours'])
        ).all()

        for p in prestations_taches:
            # Vérifier si la tâche a une échéance
            if p.date_echeance_tache:
                # Calculer les jours restants
                jours_restants = (p.date_echeance_tache - aujourd_hui).days

                # Ajouter si échéance dans les 7 prochains jours ou dépassée
                if jours_restants <= 7:
                    taches_urgentes.append({
                        'prestation_id': p.id,
                        'titre': p.titre_tache,
                        'client_nom': p.client.nom if p.client else 'Sans client',
                        'priorite': p.priorite_tache,
                        'statut': p.statut_tache,
                        'echeance': p.date_echeance_tache,
                        'jours_restants': jours_restants,
                        'en_retard': jours_restants < 0
                    })

        # Trier par échéance (les plus urgentes en premier)
        taches_urgentes.sort(key=lambda x: x['echeance'])

        # Limiter à 5 tâches maximum dans le footer
        taches_urgentes = taches_urgentes[:5]
    except:
        taches_urgentes = []

    # Retourner directement la date (pas l'objet)
    date_sauvegarde = derniere_sauv.date_sauvegarde if derniere_sauv else None

    return dict(
        factures_retard_count=factures_retard,
        paiements_retard_count=paiements_retard,
        factures_en_cours_count=factures_en_cours,
        derniere_sauvegarde=date_sauvegarde,
        jours_depuis_backup=jours_backup,
        taches_urgentes=taches_urgentes,
        now=datetime.now,  # Ajouter la fonction now pour les templates
        datetime=datetime  # Ajouter l'objet datetime pour les templates
    )

# ============================================================================
# ROUTES PRINCIPALES
# ============================================================================
# ============================================================================
# AUTHENTIFICATION ET SÉCURITÉ
# ============================================================================

def login_required(f):
    """Décorateur pour protéger les routes - redirige vers login si non connecté"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        try:
            user = Utilisateur.query.filter_by(username=username, actif=True).first()
            
            if user and user.check_password(password):
                session['user_id'] = user.id
                session['username'] = user.username
                session['user_role'] = user.role
                user.derniere_connexion = datetime.utcnow()
                db.session_presta.commit()
                flash(f'Bienvenue {user.nom or user.username} !', 'success')
                return redirect(url_for('index'))
            else:
                flash('Nom d\'utilisateur ou mot de passe incorrect.', 'error')
        except Exception as e:
            flash(f'Erreur de connexion : {str(e)}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Déconnexion"""
    session_presta.clear()
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('login'))

@app.before_request
def check_login():
    """Vérifie l'authentification avant chaque requête"""
    # Routes publiques (sans authentification)
    public_routes = ['login', 'logout', 'static', 'oauth2callback', 'google_auth']
    
    # Ne pas vérifier si c'est une route publique
    if request.endpoint and request.endpoint in public_routes:
        return None
    
    # Vérifier si l'utilisateur est connecté
    if request.endpoint and 'user_id' not in session:
        return redirect(url_for('login'))
@app.route('/')
@login_required
def index():
    """Page d'accueil - Tableau de bord"""
    # Statistiques
    total_clients = Client.query.filter_by(actif=True).count()
    total_prestations = Prestation.query.count()

    # Prestations à venir (7 prochains jours)
    date_limite = datetime.now() + timedelta(days=7)
    prestations_a_venir = Prestation.query.filter(
        Prestation.date_debut >= datetime.now(),
        Prestation.date_debut <= date_limite,
        Prestation.statut != 'Annulée'
    ).order_by(Prestation.date_debut).all()

    # Prestations en cours
    prestations_en_cours = Prestation.query.filter_by(statut='En cours').count()

    # Prestations en attente (Planifiées)
    prestations_planifiees = Prestation.query.filter_by(statut='Planifiée').count()

    # CA du mois en cours
    debut_mois = datetime.now().replace(day=1, hour=0, minute=0, second=0)
    ca_mois = db.session_presta.query(db.func.sum(Prestation.tarif_total)).filter(
        Prestation.date_debut >= debut_mois,
        Prestation.statut != 'Annulée'
    ).scalar() or 0

    # Vérifier la dernière sauvegarde (alerte si > 7 jours)
    derniere_sauvegarde = Sauvegarde.query.order_by(Sauvegarde.date_sauvegarde.desc()).first()
    afficher_alerte_backup = False
    jours_depuis_backup = None

    if derniere_sauvegarde:
        delta = datetime.now() - derniere_sauvegarde.date_sauvegarde
        jours_depuis_backup = delta.days
        if jours_depuis_backup > 7:
            afficher_alerte_backup = True
    else:
        afficher_alerte_backup = True  # Aucune sauvegarde jamais effectuée

    # Statistiques de prospection
    total_prospects = Client.query.filter_by(actif=True, statut_client='Prospect').count()
    total_clients_confirmes = Client.query.filter_by(actif=True, statut_client='Client').count()

    # Calculer le taux de conversion
    total_tous = total_prospects + total_clients_confirmes
    taux_conversion = (total_clients_confirmes / total_tous * 100) if total_tous > 0 else 0

    # Conversions ce mois (clients avec date_conversion dans le mois en cours)
    conversions_ce_mois = Client.query.filter(
        Client.actif == True,
        Client.statut_client == 'Client',
        Client.date_conversion >= debut_mois
    ).count()

    # Conversions récentes (5 dernières conversions)
    conversions_recentes = Client.query.filter(
        Client.actif == True,
        Client.statut_client == 'Client',
        Client.date_conversion.isnot(None)
    ).order_by(Client.date_conversion.desc()).limit(5).all()

    stats_prospects = {
        'total_prospects': total_prospects,
        'total_clients_confirmes': total_clients_confirmes,
        'taux_conversion': taux_conversion,
        'conversions_ce_mois': conversions_ce_mois
    }

    return render_template('dashboard.html',
                         total_clients=total_clients,
                         total_prestations=total_prestations,
                         prestations_a_venir=prestations_a_venir,
                         prestations_en_cours=prestations_en_cours,
                         prestations_planifiees=prestations_planifiees,
                         ca_mois=ca_mois,
                         afficher_alerte_backup=afficher_alerte_backup,
                         derniere_sauvegarde_complete=derniere_sauvegarde,
                         jours_depuis_backup=jours_depuis_backup,
                         stats_prospects=stats_prospects,
                         conversions_recentes=conversions_recentes)

# ============================================================================
# ROUTES CLIENTS
# ============================================================================

@app.route('/clients')
@login_required
def clients():
    """Liste des clients (hors prospects)"""
    clients = Client.query.filter_by(actif=True, statut_client='Client').order_by(Client.nom).all()
    return render_template('clients.html', clients=clients)

@app.route('/prospection')
@login_required    
def prospection():
    """Page de prospection de nouveaux clients"""
    return render_template('prospection.html')

@app.route('/liste-prospects')
@login_required    
def liste_prospects():
    """Liste des clients prospects (non encore confirmés)"""
    prospects = Client.query.filter_by(statut_client='Prospect', actif=True).order_by(Client.date_creation.desc()).all()

    # Récupérer la liste unique des villes pour le filtre
    villes_disponibles = db.session_presta.query(Client.ville).filter(
        Client.statut_client == 'Prospect',
        Client.actif == True,
        Client.ville.isnot(None),
        Client.ville != ''
    ).distinct().order_by(Client.ville).all()
    villes_disponibles = [v[0] for v in villes_disponibles]

    return render_template('liste_prospects.html',
                         prospects=prospects,
                         villes_disponibles=villes_disponibles)

@app.route('/api/prospect/<int:prospect_id>/convertir', methods=['POST'])
@login_required    
def convertir_prospect(prospect_id):
    """Convertir un prospect en client confirmé"""
    try:
        prospect = Client.query.get_or_404(prospect_id)
        prospect.statut_client = 'Client'
        prospect.date_conversion = datetime.now()  # Enregistrer la date de conversion
        db.session_presta.commit()
        return jsonify({'success': True, 'message': 'Prospect converti en client'})
    except Exception as e:
        db.session_presta.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/export-prospects-csv')
@login_required        
def export_prospects_csv():
    """Export de la liste des prospects en CSV pour téléprospection"""
    import csv
    from io import StringIO
    from flask import make_response

    prospects = Client.query.filter_by(statut_client='Prospect', actif=True).order_by(Client.date_creation.desc()).all()

    # Créer le fichier CSV en mémoire
    si = StringIO()
    writer = csv.writer(si, delimiter=';')

    # En-têtes
    writer.writerow([
        'Nom/Entreprise',
        'Contact',
        'Email',
        'Téléphone',
        'Adresse',
        'Code Postal',
        'Ville',
        'Date Ajout',
        'Notes'
    ])

    # Données
    for prospect in prospects:
        writer.writerow([
            prospect.entreprise or prospect.nom,
            f"{prospect.prenom or ''} {prospect.nom}".strip(),
            prospect.email or '',
            prospect.telephone or '',
            prospect.adresse or '',
            prospect.code_postal or '',
            prospect.ville or '',
            prospect.date_creation.strftime('%d/%m/%Y %H:%M') if prospect.date_creation else '',
            prospect.notes or ''
        ])

    # Créer la réponse avec le fichier CSV
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=prospects_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"

    return output

@app.route('/client/<int:client_id>')
@login_required
def client_detail(client_id):
    """Détail d'un client"""
    client = Client.query.get_or_404(client_id)
    prestations = Prestation.query.filter_by(client_id=client_id).order_by(Prestation.date_debut.desc()).all()
    return render_template('client_detail.html', client=client, prestations=prestations)

@app.route('/client/nouveau', methods=['GET', 'POST'])
@login_required
def client_nouveau():
    """Créer un nouveau client"""
    if request.method == 'POST':
        # Le nom du client est maintenant basé sur l'entreprise
        entreprise = request.form.get('entreprise', '').strip()
        if not entreprise:
            flash('Le nom du client / entreprise est obligatoire', 'error')
            return render_template('client_form.html', client=None)

        client = Client(
            nom=entreprise,  # Utiliser le nom de l'entreprise comme nom du client
            prenom=None,  # NULL car on utilise maintenant les contacts
            entreprise=entreprise,
            email=request.form.get('email'),
            telephone=request.form.get('telephone'),
            adresse=request.form.get('adresse'),
            code_postal=request.form.get('code_postal'),
            ville=request.form.get('ville'),
            notes=request.form.get('notes'),
            delai_paiement_jours=int(request.form.get('delai_paiement_jours', 30)),
            calendrier_google=request.form.get('calendrier_google') or None,
            statut_client=request.form.get('statut_client', 'Client')  # Par défaut 'Client', peut être 'Prospect'
        )
        db.session_presta.add(client)
        db.session_presta.commit()
        flash('Client créé avec succès !', 'success')
        return redirect(url_for('clients'))

    # Récupérer la liste des calendriers Google disponibles
    calendriers = []
    try:
        service = get_calendar_service()
        if service:
            calendriers = get_filtered_calendars(service)
    except:
        pass

    return render_template('client_form.html', client=None, calendriers=calendriers)

@app.route('/client/<int:client_id>/modifier', methods=['GET', 'POST'])
@login_required
def client_modifier(client_id):
    """Modifier un client"""
    client = Client.query.get_or_404(client_id)

    if request.method == 'POST':
        # Le nom du client est maintenant basé sur l'entreprise
        entreprise = request.form.get('entreprise', '').strip()
        if not entreprise:
            flash('Le nom du client / entreprise est obligatoire', 'error')
            return render_template('client_form.html', client=client)

        client.nom = entreprise  # Utiliser le nom de l'entreprise comme nom du client
        client.prenom = None  # NULL car on utilise maintenant les contacts
        client.entreprise = entreprise
        client.email = request.form.get('email')
        client.telephone = request.form.get('telephone')
        client.adresse = request.form.get('adresse')
        client.code_postal = request.form.get('code_postal')
        client.ville = request.form.get('ville')
        client.notes = request.form.get('notes')
        client.delai_paiement_jours = int(request.form.get('delai_paiement_jours', 30))
        client.calendrier_google = request.form.get('calendrier_google') or None

        db.session_presta.commit()
        flash('Client modifié avec succès !', 'success')
        return redirect(url_for('client_detail', client_id=client_id))

    # Récupérer la liste des calendriers Google disponibles
    calendriers = []
    try:
        service = get_calendar_service()
        if service:
            calendriers = get_filtered_calendars(service)
    except:
        pass

    return render_template('client_form.html', client=client, calendriers=calendriers)

@app.route('/client/<int:client_id>/supprimer', methods=['POST'])
@login_required
def client_supprimer(client_id):
    """Supprimer (désactiver) un client ou un prospect"""
    try:
        client = Client.query.get_or_404(client_id)
        etait_prospect = (client.statut_client == 'Prospect')
        client.actif = False
        db.session_presta.commit()

        # Si requête AJAX (depuis liste_prospects), retourner JSON
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'message': 'Prospect supprimé avec succès !' if etait_prospect else 'Client supprimé avec succès !',
                'redirect': url_for('liste_prospects') if etait_prospect else url_for('clients')
            })

        # Sinon redirection classique (formulaires HTML)
        if etait_prospect:
            flash('Prospect supprimé avec succès !', 'success')
            return redirect(url_for('liste_prospects'))
        else:
            flash('Client supprimé avec succès !', 'success')
            return redirect(url_for('clients'))
    except Exception as e:
        db.session_presta.rollback()
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'success': False, 'message': str(e)}), 500
        else:
            flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
            return redirect(url_for('clients'))

# ============================================================================
# ROUTES CONTACTS
# ============================================================================

@app.route('/client/<int:client_id>/contact/nouveau', methods=['GET', 'POST'])
def contact_nouveau(client_id):
    """Créer un nouveau contact pour un client"""
    client = Client.query.get_or_404(client_id)

    if request.method == 'POST':
        contact = Contact(
            client_id=client_id,
            nom=request.form['nom'],
            prenom=request.form.get('prenom'),
            poste=request.form.get('poste'),
            tel_fixe=request.form.get('tel_fixe'),
            tel_portable=request.form.get('tel_portable'),
            email=request.form.get('email'),
            notes=request.form.get('notes')
        )
        db.session_presta.add(contact)
        db.session_presta.commit()
        flash('Contact créé avec succès !', 'success')
        return redirect(url_for('client_detail', client_id=client_id))

    return render_template('contact_form.html', contact=None, client=client)

@app.route('/contact/<int:contact_id>/modifier', methods=['GET', 'POST'])
def contact_modifier(contact_id):
    """Modifier un contact"""
    contact = Contact.query.get_or_404(contact_id)
    client = contact.client

    if request.method == 'POST':
        contact.nom = request.form['nom']
        contact.prenom = request.form.get('prenom')
        contact.poste = request.form.get('poste')
        contact.tel_fixe = request.form.get('tel_fixe')
        contact.tel_portable = request.form.get('tel_portable')
        contact.email = request.form.get('email')
        contact.notes = request.form.get('notes')

        db.session_presta.commit()
        flash('Contact modifié avec succès !', 'success')
        return redirect(url_for('client_detail', client_id=client.id))

    return render_template('contact_form.html', contact=contact, client=client)

@app.route('/contact/<int:contact_id>/supprimer', methods=['POST'])
def contact_supprimer(contact_id):
    """Supprimer (désactiver) un contact"""
    contact = Contact.query.get_or_404(contact_id)
    client_id = contact.client_id
    contact.actif = False
    db.session_presta.commit()
    flash('Contact supprimé avec succès !', 'success')
    return redirect(url_for('client_detail', client_id=client_id))

# ============================================================================
# ROUTES PRESTATIONS
# ============================================================================

@app.route('/prestations')
def prestations():
    """Liste des prestations"""
    filtre_statut = request.args.get('statut', 'all')

    query = Prestation.query

    if filtre_statut != 'all':
        query = query.filter_by(statut=filtre_statut)

    prestations = query.order_by(Prestation.date_debut.desc()).all()
    return render_template('prestations.html', prestations=prestations, filtre_statut=filtre_statut)


@app.route('/ouvrir_commande/<int:prestation_id>')
def ouvrir_commande(prestation_id):
    """Ouvre le PDF de commande - Format: AAAAMMJJ-JJMMAAAA.pdf"""
    prestation = Prestation.query.get_or_404(prestation_id)

    try:
        date_presta_str = prestation.date_debut.strftime('%Y%m%d')
        if prestation.date_demande:
            date_commande_str = prestation.date_demande.strftime('%d%m%Y')
        else:
            date_commande_str = prestation.date_creation.strftime('%d%m%Y')

        filename = f"{date_presta_str}-{date_commande_str}.pdf"

        base_path = Path(r"G:\Mon Drive\mib-prevention\entreprise_michel\client")
        client_folder = base_path / prestation.client.entreprise / "commande"

        annee = prestation.date_debut.year
        folders = [
            client_folder / str(annee),
            client_folder / str(annee - 1),
            client_folder / str(annee + 1),
        ]

        file_found = None
        for folder in folders:
            if folder.exists():
                potential_file = folder / filename
                if potential_file.exists():
                    file_found = potential_file
                    break

        if file_found:
            if sys.platform == 'win32':
                os.startfile(str(file_found))
            flash(f"Ouverture: {filename}", 'success')
        else:
            flash(f"Fichier non trouvé: {filename}", 'warning')

    except Exception as e:
        flash(f"Erreur: {str(e)}", 'error')

    return redirect(url_for('prestation_detail', prestation_id=prestation_id))


@app.route('/prestation/<int:prestation_id>')
def prestation_detail(prestation_id):
    """Détail d'une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)
    return render_template('prestation_detail.html', prestation=prestation)

@app.route('/prestation/<int:prestation_id>/tarifs', methods=['POST'])
def prestation_sauvegarder_tarifs(prestation_id):
    """Sauvegarder les lignes de tarif détaillées de la prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)

    # Supprimer les anciennes lignes
    LignePrestationDeplacement.query.filter_by(prestation_id=prestation_id).delete()
    LignePrestationFourniture.query.filter_by(prestation_id=prestation_id).delete()
    LignePrestationTarif.query.filter_by(prestation_id=prestation_id).delete()

    # Traiter les lignes de déplacement
    codes_dep = request.form.getlist('deplacement_code[]')
    types_dep = request.form.getlist('deplacement_type[]')
    nbres_dep = request.form.getlist('deplacement_nbre[]')
    pus_dep = request.form.getlist('deplacement_pu_ht[]')
    pts_dep = request.form.getlist('deplacement_pt_ht[]')

    total_deplacement = 0
    for i in range(len(codes_dep)):
        if types_dep[i].strip():  # Ne créer que si le type n'est pas vide
            ligne = LignePrestationDeplacement(
                prestation_id=prestation_id,
                code=codes_dep[i].strip() or None,
                type=types_dep[i].strip(),
                nbre=float(nbres_dep[i]) if nbres_dep[i] else 0,
                pu_ht=float(pus_dep[i]) if pus_dep[i] else 0,
                pt_ht=float(pts_dep[i]) if pts_dep[i] else 0
            )
            db.session_presta.add(ligne)
            total_deplacement += ligne.pt_ht

    # Traiter les lignes de fourniture
    codes_four = request.form.getlist('fourniture_code[]')
    types_four = request.form.getlist('fourniture_type[]')
    nbres_four = request.form.getlist('fourniture_nbre[]')
    pus_four = request.form.getlist('fourniture_pu_ht[]')
    pts_four = request.form.getlist('fourniture_pt_ht[]')

    total_fourniture = 0
    for i in range(len(codes_four)):
        if types_four[i].strip():
            ligne = LignePrestationFourniture(
                prestation_id=prestation_id,
                code=codes_four[i].strip() or None,
                type=types_four[i].strip(),
                nbre=float(nbres_four[i]) if nbres_four[i] else 0,
                pu_ht=float(pus_four[i]) if pus_four[i] else 0,
                pt_ht=float(pts_four[i]) if pts_four[i] else 0
            )
            db.session_presta.add(ligne)
            total_fourniture += ligne.pt_ht

    # Traiter les lignes de prestation/tarif
    codes_prest = request.form.getlist('prestation_code[]')
    types_prest = request.form.getlist('prestation_type[]')
    nbres_prest = request.form.getlist('prestation_nbre[]')
    pus_prest = request.form.getlist('prestation_pu_ht[]')
    pts_prest = request.form.getlist('prestation_pt_ht[]')

    total_prestation = 0
    for i in range(len(codes_prest)):
        if types_prest[i].strip():
            ligne = LignePrestationTarif(
                prestation_id=prestation_id,
                code=codes_prest[i].strip() or None,
                type=types_prest[i].strip(),
                nbre=float(nbres_prest[i]) if nbres_prest[i] else 0,
                pu_ht=float(pus_prest[i]) if pus_prest[i] else 0,
                pt_ht=float(pts_prest[i]) if pts_prest[i] else 0
            )
            db.session_presta.add(ligne)
            total_prestation += ligne.pt_ht

    # Mettre à jour les totaux globaux dans la prestation (pour compatibilité)
    prestation.frais_deplacement = total_deplacement
    prestation.frais_fournitures = total_fourniture
    prestation.tarif_total = total_prestation

    db.session_presta.commit()

    flash('Tarifs de la prestation sauvegardés avec succès !', 'success')
    return redirect(url_for('prestation_detail', prestation_id=prestation_id))


@app.route('/prestation/<int:prestation_id>/modifier-statut', methods=['POST'])
def modifier_statut_prestation(prestation_id):
    """Modification manuelle du statut d'une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)
    nouveau_statut = request.form.get('nouveau_statut')

    if nouveau_statut in ['Planifiée', 'En cours', 'Terminée', 'Annulée']:
        prestation.statut = nouveau_statut
        db.session_presta.commit()
        flash(f'Statut modifié: {nouveau_statut}', 'success')
    else:
        flash('Statut invalide', 'error')

    return redirect(url_for('prestation_detail', prestation_id=prestation.id))

@app.route('/prestation/nouvelle', methods=['GET', 'POST'])
def prestation_nouvelle():
    """Créer une nouvelle prestation"""
    if request.method == 'POST':
        # Générer automatiquement le titre à partir du type ou du thème
        titre_auto = request.form.get('type_prestation') or request.form['theme_prestation']

        # Récupérer les données des sessions
        sessions_dates_debut = request.form.getlist('sessions_date_debut[]')
        sessions_dates_fin = request.form.getlist('sessions_date_fin[]')
        sessions_creneaux = request.form.getlist('sessions_creneau[]')
        sessions_durees = request.form.getlist('sessions_duree[]')
        sessions_heures_debut = request.form.getlist('sessions_heure_debut[]')
        sessions_heures_fin = request.form.getlist('sessions_heure_fin[]')
        sessions_journee_complete = request.form.getlist('sessions_journee_complete[]')

        print("🔴🔴🔴 DEBUG FORMULAIRE 🔴🔴🔴")
        print("sessions_creneaux:", sessions_creneaux)
        print("sessions_journee_complete:", sessions_journee_complete)
        print("calendrier_id du formulaire:", request.form.get('calendrier_id'))
        print("🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴")

        prestation = Prestation(
            # Client et demande
            client_id=request.form['client_id'],
            demandeur=request.form.get('demandeur'),
            date_demande=datetime.strptime(request.form['date_demande'], '%Y-%m-%d').date() if request.form.get('date_demande') else None,
            reference_commande=request.form.get('reference_commande'),
            # Thème, domaine et type
            theme_prestation=request.form['theme_prestation'],
            domaine_prestation=request.form.get('domaine_prestation'),
            type_prestation=request.form.get('type_prestation'),
            titre=titre_auto,
            description=request.form.get('description'),
            # Dates : seront remplies après création des sessions
            date_debut=None,
            date_fin=None,
            duree_heures=None,
            creneau=None,
            journee_entiere=False,
            # Lieu
            lieu=request.form.get('lieu'),
            adresse_prestation=request.form.get('adresse_prestation'),
            code_postal_prestation=request.form.get('code_postal_prestation'),
            ville_prestation=request.form.get('ville_prestation'),
            distance_km=float(request.form['distance_km']) if request.form.get('distance_km') else None,
            duree_trajet_minutes=int(request.form['duree_trajet_minutes']) if request.form.get('duree_trajet_minutes') else None,
            # Participants et logistique
            nb_stagiaires=int(request.form['nb_stagiaires']) if request.form.get('nb_stagiaires') else None,
            nb_repas=int(request.form['nb_repas']) if request.form.get('nb_repas') else None,
            nb_hebergements=int(request.form['nb_hebergements']) if request.form.get('nb_hebergements') else None,
            # Financier
            tarif_horaire=float(request.form['tarif_horaire']) if request.form.get('tarif_horaire') else None,
            tarif_total=float(request.form['tarif_total']) if request.form.get('tarif_total') else None,
            # Statut et commentaires
            statut=request.form.get('statut', 'Planifiée'),
            commentaires=request.form.get('commentaires'),
            notes=request.form.get('notes'),
            # Champs de tâche
            titre_tache=request.form.get('titre_tache'),
            description_tache=request.form.get('description_tache'),
            date_debut_tache=datetime.fromisoformat(request.form['date_debut_tache']) if request.form.get('date_debut_tache') else None,
            date_echeance_tache=datetime.fromisoformat(request.form['date_echeance_tache']) if request.form.get('date_echeance_tache') else None,
            priorite_tache=request.form.get('priorite_tache', 'Moyenne'),
            statut_tache=request.form.get('statut_tache', 'À faire'),
            # Google Calendar
            calendrier_id=request.form.get('calendrier_id') or None
        )

        # IMPORTANT : Remplir date_debut AVANT le flush pour éviter l'erreur NOT NULL
        # Traiter la première session en premier pour avoir date_debut
        if sessions_dates_debut and sessions_dates_debut[0]:
            creneau_0 = sessions_creneaux[0] if len(sessions_creneaux) > 0 else ''
            heure_debut_str = '08:00'
            heure_fin_str = '18:00'

            if creneau_0 == 'Matin':
                heure_debut_str = '08:00'
                heure_fin_str = '12:00'
            elif creneau_0 == 'Après-midi':
                heure_debut_str = '13:00'
                heure_fin_str = '17:00'
            elif creneau_0 == 'Journée':
                heure_debut_str = '08:00'
                heure_fin_str = '20:00'
            elif creneau_0 == 'Personnalisé':
                if len(sessions_heures_debut) > 0:
                    heure_debut_str = sessions_heures_debut[0] or '08:00'
                if len(sessions_heures_fin) > 0:
                    heure_fin_str = sessions_heures_fin[0] or '18:00'

            date_debut_premiere = datetime.strptime(f"{sessions_dates_debut[0]} {heure_debut_str}", '%Y-%m-%d %H:%M')
            date_fin_str_premiere = sessions_dates_fin[0] if len(sessions_dates_fin) > 0 and sessions_dates_fin[0] else sessions_dates_debut[0]
            date_fin_premiere = datetime.strptime(f"{date_fin_str_premiere} {heure_fin_str}", '%Y-%m-%d %H:%M')
            journee_complete_premiere = '1' in sessions_journee_complete or creneau_0 == 'Journée'
            duree_premiere = float(sessions_durees[0]) if len(sessions_durees) > 0 and sessions_durees[0] else None

            # Remplir les dates principales avec la première session
            prestation.date_debut = date_debut_premiere
            prestation.date_fin = date_fin_premiere
            prestation.duree_heures = duree_premiere
            prestation.creneau = creneau_0
            prestation.journee_entiere = journee_complete_premiere

        db.session_presta.add(prestation)
        db.session_presta.flush()  # Pour obtenir l'ID (maintenant date_debut est rempli)

        # Créer les sessions
        for i, date_debut_str in enumerate(sessions_dates_debut):
            if not date_debut_str:
                continue

            creneau = sessions_creneaux[i] if i < len(sessions_creneaux) else ''
            heure_debut_str = '08:00'
            heure_fin_str = '18:00'

            if creneau == 'Matin':
                heure_debut_str = '08:00'
                heure_fin_str = '12:00'
            elif creneau == 'Après-midi':
                heure_debut_str = '13:00'
                heure_fin_str = '17:00'
            elif creneau == 'Journée':
                heure_debut_str = '08:00'
                heure_fin_str = '20:00'
            elif creneau == 'Personnalisé':
                if i < len(sessions_heures_debut):
                    heure_debut_str = sessions_heures_debut[i] or '08:00'
                if i < len(sessions_heures_fin):
                    heure_fin_str = sessions_heures_fin[i] or '18:00'

            date_debut = datetime.strptime(f"{date_debut_str} {heure_debut_str}", '%Y-%m-%d %H:%M')
            date_fin_str = sessions_dates_fin[i] if i < len(sessions_dates_fin) and sessions_dates_fin[i] else date_debut_str
            date_fin = datetime.strptime(f"{date_fin_str} {heure_fin_str}", '%Y-%m-%d %H:%M')

            journee_complete = str(i + 1) in sessions_journee_complete or creneau == 'Journée'
            duree = float(sessions_durees[i]) if i < len(sessions_durees) and sessions_durees[i] else None

            print(f"⚡ SESSION {i+1}: creneau='{creneau}', journee_complete={journee_complete}")

            session = SessionPrestation(
                prestation_id=prestation.id,
                date_debut=date_debut,
                date_fin=date_fin,
                duree_heures=duree,
                journee_complete=journee_complete,
                ordre=i
            )
            db.session_presta.add(session)

        db.session_presta.commit()

        # NOUVEAU SYSTÈME : Synchronisation Google Calendar avec rappels personnalisés
        print("\n" + "🔄" * 40)
        print("NOUVEAU SYSTÈME DE SYNCHRONISATION GOOGLE CALENDAR")
        print("🔄" * 40 + "\n")

        try:
            # Récupérer le client
            client = Client.query.get(prestation.client_id)

            print("🔵🔵🔵 DEBUG AVANT GOOGLE CALENDAR 🔵🔵🔵")
            print("prestation.calendrier_id:", prestation.calendrier_id)
            print("client.calendrier_google:", client.calendrier_google if client else "None")
            print("🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵")

            # Utiliser la NOUVELLE fonction avec logique de sélection de calendrier :
            # 1. prestation.calendrier_id (si défini)
            # 2. client.calendrier_google (si défini)
            # 3. calendrier principal (par défaut)
            success, message, event_id = sync_prestation_to_gcal(prestation.id)

            if success:
                prestation.gcal_event_id = event_id
                prestation.gcal_synced = True
                prestation.gcal_last_sync = datetime.utcnow()
                db.session_presta.commit()
                flash(f'✓ Prestation créée et synchronisée avec Google Calendar ! {message}', 'success')
            else:
                flash(f'⚠️ Prestation créée mais sync Google Calendar échouée : {message}', 'warning')

        except Exception as ex:
            print(f"❌ ERREUR sync Google Calendar: {str(ex)}")
            import traceback
            traceback.print_exc()
            flash('Prestation créée avec succès (sync Google Calendar échouée)', 'warning')

        return redirect(url_for('prestation_detail', prestation_id=prestation.id))

    clients = Client.query.filter_by(actif=True).order_by(Client.nom).all()

    # DÉSACTIVÉ : Récupération des calendriers Google (cause timeout de 20-30s)
    # La liste des calendriers n'est pas utilisée dans le formulaire
    # Le calendrier est sélectionné automatiquement via client.calendrier_google
    calendriers = []
    # try:
    #     service = get_calendar_service()
    #     if service:
    #         calendriers = get_filtered_calendars(service)
    # except:
    #     pass

    return render_template('prestation_form.html', prestation=None, clients=clients, calendriers=calendriers)

@app.route('/prestation/<int:prestation_id>/modifier', methods=['GET', 'POST'])
def prestation_modifier(prestation_id):
    """Modifier une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)

    if request.method == 'POST':
        # Sauvegarder l'ancien statut pour détecter si annulée
        ancien_statut = prestation.statut
        etait_synchronisee = prestation.gcal_synced

        # Générer automatiquement le titre à partir du type ou du thème
        titre_auto = request.form.get('type_prestation') or request.form['theme_prestation']

        # Récupérer les données des sessions
        sessions_dates_debut = request.form.getlist('sessions_date_debut[]')
        sessions_dates_fin = request.form.getlist('sessions_date_fin[]')
        sessions_creneaux = request.form.getlist('sessions_creneau[]')
        sessions_durees = request.form.getlist('sessions_duree[]')
        sessions_heures_debut = request.form.getlist('sessions_heure_debut[]')
        sessions_heures_fin = request.form.getlist('sessions_heure_fin[]')
        sessions_journee_complete = request.form.getlist('sessions_journee_complete[]')
        sessions_ids = request.form.getlist('sessions_id[]')

        # Client et demande
        prestation.client_id = request.form['client_id']
        prestation.demandeur = request.form.get('demandeur')
        prestation.date_demande = datetime.strptime(request.form['date_demande'], '%Y-%m-%d').date() if request.form.get('date_demande') else None
        prestation.reference_commande = request.form.get('reference_commande')
        # Thème, domaine et type
        prestation.theme_prestation = request.form['theme_prestation']
        prestation.domaine_prestation = request.form.get('domaine_prestation')
        prestation.type_prestation = request.form.get('type_prestation')
        prestation.titre = titre_auto
        prestation.description = request.form.get('description')
        # Lieu
        prestation.lieu = request.form.get('lieu')
        prestation.adresse_prestation = request.form.get('adresse_prestation')
        prestation.code_postal_prestation = request.form.get('code_postal_prestation')
        prestation.ville_prestation = request.form.get('ville_prestation')
        prestation.distance_km = float(request.form['distance_km']) if request.form.get('distance_km') else None
        prestation.duree_trajet_minutes = int(request.form['duree_trajet_minutes']) if request.form.get('duree_trajet_minutes') else None
        # Participants et logistique
        prestation.nb_stagiaires = int(request.form['nb_stagiaires']) if request.form.get('nb_stagiaires') else None
        prestation.nb_repas = int(request.form['nb_repas']) if request.form.get('nb_repas') else None
        prestation.nb_hebergements = int(request.form['nb_hebergements']) if request.form.get('nb_hebergements') else None
        # Financier
        prestation.tarif_horaire = float(request.form['tarif_horaire']) if request.form.get('tarif_horaire') else None
        prestation.tarif_total = float(request.form['tarif_total']) if request.form.get('tarif_total') else None
        # Statut et commentaires
        prestation.statut = request.form.get('statut', 'Planifiée')
        prestation.commentaires = request.form.get('commentaires')
        prestation.notes = request.form.get('notes')
        # Champs de tâche
        prestation.titre_tache = request.form.get('titre_tache')
        prestation.description_tache = request.form.get('description_tache')
        prestation.date_debut_tache = datetime.fromisoformat(request.form['date_debut_tache']) if request.form.get('date_debut_tache') else None
        prestation.date_echeance_tache = datetime.fromisoformat(request.form['date_echeance_tache']) if request.form.get('date_echeance_tache') else None
        prestation.priorite_tache = request.form.get('priorite_tache', 'Moyenne')
        prestation.statut_tache = request.form.get('statut_tache', 'À faire')
        # Google Calendar
        prestation.calendrier_id = request.form.get('calendrier_id') or None

        # Gérer les sessions : supprimer celles qui n'existent plus et créer/mettre à jour
        existing_session_ids = set()
        for i, date_debut_str in enumerate(sessions_dates_debut):
            if not date_debut_str:
                continue

            session_id = sessions_ids[i] if i < len(sessions_ids) and sessions_ids[i] else None

            creneau = sessions_creneaux[i] if i < len(sessions_creneaux) else ''
            heure_debut_str = '08:00'
            heure_fin_str = '18:00'

            if creneau == 'Matin':
                heure_debut_str = '08:00'
                heure_fin_str = '12:00'
            elif creneau == 'Après-midi':
                heure_debut_str = '13:00'
                heure_fin_str = '17:00'
            elif creneau == 'Journée':
                heure_debut_str = '08:00'
                heure_fin_str = '20:00'
            elif creneau == 'Personnalisé':
                if i < len(sessions_heures_debut):
                    heure_debut_str = sessions_heures_debut[i] or '08:00'
                if i < len(sessions_heures_fin):
                    heure_fin_str = sessions_heures_fin[i] or '18:00'

            date_debut = datetime.strptime(f"{date_debut_str} {heure_debut_str}", '%Y-%m-%d %H:%M')
            date_fin_str = sessions_dates_fin[i] if i < len(sessions_dates_fin) and sessions_dates_fin[i] else date_debut_str
            date_fin = datetime.strptime(f"{date_fin_str} {heure_fin_str}", '%Y-%m-%d %H:%M')

            journee_complete = str(i + 1) in sessions_journee_complete or creneau == 'Journée'
            duree = float(sessions_durees[i]) if i < len(sessions_durees) and sessions_durees[i] else None

            if session_id:
                # Mettre à jour session existante
                session = SessionPrestation.query.get(session_id)
                if session:
                    session_presta.date_debut = date_debut
                    session_presta.date_fin = date_fin
                    session_presta.duree_heures = duree
                    session_presta.journee_complete = journee_complete
                    session_presta.ordre = i
                    existing_session_ids.add(int(session_id))
            else:
                # Créer nouvelle session
                session = SessionPrestation(
                    prestation_id=prestation.id,
                    date_debut=date_debut,
                    date_fin=date_fin,
                    duree_heures=duree,
                    journee_complete=journee_complete,
                    ordre=i
                )
                db.session_presta.add(session)

            # Première session = dates principales (compatibilité)
            if i == 0:
                prestation.date_debut = date_debut
                prestation.date_fin = date_fin
                prestation.duree_heures = duree
                prestation.creneau = creneau
                prestation.journee_entiere = journee_complete

        # Supprimer les sessions qui ont été retirées
        for session_presta in prestation.sessions:
            if session_presta.id not in existing_session_ids:
                db.session_presta.delete(session)

        db.session_presta.commit()

        # Gestion automatique Google Calendar
        try:
            nouveau_statut = prestation.statut

            # Si la prestation passe à "Annulée" et était synchronisée → supprimer de Google Calendar
            if nouveau_statut == 'Annulée' and etait_synchronisee:
                success, message = delete_gcal_event(prestation_id)
                if success:
                    flash(f'✓ Prestation annulée et supprimée de Google Calendar', 'success')
                else:
                    flash(f'✓ Prestation modifiée (échec suppression Google Calendar : {message})', 'warning')

            # Si la prestation était déjà synchronisée et n'est PAS annulée → mettre à jour
            elif etait_synchronisee and nouveau_statut != 'Annulée':
                success, message, event_id = sync_prestation_to_gcal(prestation_id)
                if success:
                    flash(f'✓ Prestation modifiée et mise à jour sur Google Calendar', 'success')
                else:
                    flash(f'✓ Prestation modifiée (échec mise à jour Google Calendar : {message})', 'warning')

            else:
                flash('Prestation modifiée avec succès !', 'success')

        except:
            flash('Prestation modifiée avec succès !', 'success')

        return redirect(url_for('prestation_detail', prestation_id=prestation_id))

    clients = Client.query.filter_by(actif=True).order_by(Client.nom).all()

    # Migration automatique : Si la prestation n'a pas de sessions mais a date_debut/date_fin,
    # créer une session à partir de ces dates
    if prestation and not prestation.sessions and prestation.date_debut:
        session = SessionPrestation(
            prestation_id=prestation.id,
            date_debut=prestation.date_debut,
            date_fin=prestation.date_fin if prestation.date_fin else prestation.date_debut,
            duree_heures=prestation.duree_heures,
            journee_complete=False,
            ordre=1
        )
        db.session_presta.add(session)
        db.session_presta.commit()
        # Recharger la prestation pour avoir les sessions
        db.session_presta.refresh(prestation)

    # DÉSACTIVÉ : Récupération des calendriers Google (cause timeout de 20-30s)
    # La liste des calendriers n'est pas utilisée dans le formulaire
    # Le calendrier est sélectionné automatiquement via client.calendrier_google
    calendriers = []
    # try:
    #     service = get_calendar_service()
    #     if service:
    #         calendriers = get_filtered_calendars(service)
    # except:
    #     pass

    return render_template('prestation_form.html', prestation=prestation, clients=clients, calendriers=calendriers)

@app.route('/prestation/<int:prestation_id>/supprimer', methods=['POST'])
def prestation_supprimer(prestation_id):
    """Supprimer une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)

    # Supprimer les événements Google Calendar associés
    gcal_message = None
    if prestation.gcal_event_id:
        try:
            success, message = delete_gcal_event(prestation_id)
            if success:
                gcal_message = message
            else:
                flash(f'⚠️ Échec suppression Google Calendar : {message}', 'warning')
        except Exception as e:
            flash(f'⚠️ Erreur Google Calendar : {str(e)}', 'warning')

    # Supprimer la prestation de la base de données
    # La relation cascade='all, delete-orphan' supprimera automatiquement les blocages
    db.session_presta.delete(prestation)
    db.session_presta.commit()

    # Message de succès
    if gcal_message:
        flash(f'✓ Prestation supprimée ! {gcal_message}', 'success')
    else:
        flash('✓ Prestation supprimée avec succès !', 'success')

    return redirect(url_for('prestations'))

# ============================================================================
# ROUTES INDISPONIBILITÉ
# ============================================================================

@app.route('/indisponibilite')
def indisponibilite():
    """Page de gestion des indisponibilités"""
    indisponibilites = Indisponibilite.query.order_by(Indisponibilite.date_debut.desc()).all()
    return render_template('indisponibilite.html', indisponibilites=indisponibilites)

@app.route('/indisponibilite/creer', methods=['POST'])
def creer_indisponibilite():
    """Créer une nouvelle période d'indisponibilité sur tous les calendriers"""
    try:
        date_debut = datetime.strptime(request.form['date_debut'], '%Y-%m-%d').date()
        date_fin = datetime.strptime(request.form['date_fin'], '%Y-%m-%d').date()
        motif = request.form['motif']
        note = request.form.get('note', '')

        # Créer l'indisponibilité
        indispo = Indisponibilite(
            date_debut=date_debut,
            date_fin=date_fin,
            motif=motif,
            note=note
        )
        db.session_presta.add(indispo)
        db.session_presta.flush()

        # Synchroniser avec Google Calendar sur TOUS les calendriers filtrés
        gcal_events_dict = {}

        if GOOGLE_CALENDAR_AVAILABLE:
            service = get_calendar_service()
            if service:
                # Récupérer tous les calendriers filtrés (professionnels uniquement)
                calendars = get_filtered_calendars(service)

                # === RAPPELS POUR INDISPONIBILITÉS ===
                reminders_list = []
                try:

                    if date_debut:
                        # Pour indisponibilité, prendre 8h00 le jour de début
                        event_start_dt = datetime.combine(date_debut, datetime.min.time().replace(hour=8))

                        # Rappel la veille à 19h00
                        reminder_veille = event_start_dt.replace(hour=19, minute=0) - timedelta(days=1)
                        minutes_veille = int((event_start_dt - reminder_veille).total_seconds() / 60)
                        if minutes_veille > 0 and minutes_veille < 40320:
                            reminders_list.append({'method': 'popup', 'minutes': minutes_veille})
                except Exception as e:
                    pass
                # === FIN RAPPELS ===

                # Créer l'événement sur chaque calendrier
                for calendar in calendars:
                    try:
                        event_data = {
                            'summary': f'🚫 INDISPONIBLE - {motif}',
                            'description': note or f'Indisponibilité : {motif}',
                            'start': {
                                'date': date_debut.strftime('%Y-%m-%d'),
                            },
                            'end': {
                                'date': (date_fin + timedelta(days=1)).strftime('%Y-%m-%d'),  # Date de fin exclusive
                            },
                            'transparency': 'opaque',  # Bloque le calendrier
                            'colorId': '11',  # Rouge pour indisponibilité
                            'reminders': {
                                'useDefault': False,
                                'overrides': reminders_list
                            } if reminders_list else {'useDefault': True}
                        }

                        print("!!! CREATION INDISPONIBILITE - LIGNE 1807 !!!")
                        print("event_data reminders:", event_data.get('reminders'))

                        event = service.events().insert(
                            calendarId=calendar['id'],
                            body=event_data
                        ).execute()

                        print("!!! INDISPONIBILITE CREEE - ID:", event['id'])
                        gcal_events_dict[calendar['id']] = event['id']
                    except Exception as e:
                        print(f"Erreur création événement sur calendrier {calendar.get('summary', 'Inconnu')}: {e}")

        # Sauvegarder les IDs d'événements
        indispo.gcal_events = json.dumps(gcal_events_dict)
        db.session_presta.commit()

        nb_calendriers = len(gcal_events_dict)
        if nb_calendriers > 0:
            flash(f'✓ Indisponibilité créée sur {nb_calendriers} calendrier(s) !', 'success')
        else:
            flash('✓ Indisponibilité créée (Google Calendar non configuré)', 'success')

    except Exception as e:
        db.session_presta.rollback()
        flash(f'❌ Erreur : {str(e)}', 'danger')

    return redirect(url_for('indisponibilite'))

@app.route('/indisponibilite/<int:indispo_id>/supprimer', methods=['POST'])
def supprimer_indisponibilite(indispo_id):
    """Supprimer une indisponibilité et ses événements Google Calendar"""
    indispo = Indisponibilite.query.get_or_404(indispo_id)

    # Supprimer les événements Google Calendar
    if indispo.gcal_events and GOOGLE_CALENDAR_AVAILABLE:
        service = get_calendar_service()
        if service:
            try:
                events_dict = json.loads(indispo.gcal_events)
                for calendar_id, event_id in events_dict.items():
                    try:
                        service.events().delete(
                            calendarId=calendar_id,
                            eventId=event_id
                        ).execute()
                    except Exception as e:
                        print(f"Erreur suppression événement {event_id}: {e}")
            except:
                pass

    db.session_presta.delete(indispo)
    db.session_presta.commit()

    flash('✓ Indisponibilité supprimée !', 'success')
    return redirect(url_for('indisponibilite'))

@app.route('/prestation/<int:prestation_id>/tarif', methods=['GET', 'POST'])
def prestation_tarif(prestation_id):
    """Gérer le tarif d'une prestation (tarif, frais fournitures, frais déplacement)"""
    prestation = Prestation.query.get_or_404(prestation_id)

    if request.method == 'POST':
        # Mettre à jour les tarifs
        prestation.tarif_total = float(request.form['tarif_total']) if request.form.get('tarif_total') else None
        prestation.frais_fournitures = float(request.form['frais_fournitures']) if request.form.get('frais_fournitures') else None
        prestation.frais_deplacement = float(request.form['frais_deplacement']) if request.form.get('frais_deplacement') else None

        db.session_presta.commit()
        flash('Tarif mis à jour avec succès !', 'success')
        return redirect(url_for('prestation_detail', prestation_id=prestation_id))

    return render_template('prestation_tarif.html', prestation=prestation)

@app.route('/api/prestation/<int:prestation_id>/statut', methods=['POST'])
def prestation_update_statut(prestation_id):
    """Mettre à jour le statut d'une prestation (AJAX)"""
    prestation = Prestation.query.get_or_404(prestation_id)

    data = request.get_json()
    statut_type = data.get('type')  # 'facture', 'devis' ou 'paiement'
    nouveau_statut = data.get('statut')

    if statut_type == 'facture':
        prestation.statut_facture = nouveau_statut
    elif statut_type == 'devis':
        prestation.statut_devis = nouveau_statut
    elif statut_type == 'paiement':
        prestation.statut_paiement = nouveau_statut
    else:
        return jsonify({'success': False, 'error': 'Type de statut invalide'}), 400

    db.session_presta.commit()

    return jsonify({
        'success': True,
        'message': f'Statut {statut_type} mis à jour',
        'nouveau_statut': nouveau_statut
    })

# ============================================================================
# ROUTES CALENDRIER
# ============================================================================

@app.route('/calendrier')
def calendrier():
    """Vue calendrier"""
    return render_template('calendrier.html')

@app.route('/api/prestations/calendrier')
def api_prestations_calendrier():
    """API pour récupérer les prestations ET indisponibilités au format calendrier"""
    # Récupérer le paramètre 'jours' (défaut: toutes les prestations)
    jours = request.args.get('jours', type=int)

    query = Prestation.query.filter(Prestation.statut != 'Annulée')

    # Si paramètre jours fourni, filtrer les prestations
    if jours:
        date_limite = datetime.now() + timedelta(days=jours)
        query = query.filter(
            Prestation.date_debut >= datetime.now(),
            Prestation.date_debut <= date_limite
        )

    prestations = query.order_by(Prestation.date_debut).all()

    events = []

    # 1. Ajouter les prestations
    for p in prestations:
        color = {
            'Planifiée': '#5D5CDE',
            'En cours': '#FF9800',
            'Terminée': '#4CAF50',
            'Annulée': '#F44336'
        }.get(p.statut, '#5D5CDE')

        # Construire le nom client sans "None"
        client_nom = ''
        if p.client:
            if p.client.prenom:
                client_nom = p.client.prenom + ' ' + p.client.nom
            else:
                client_nom = p.client.nom

        # Afficher une entrée par session (pas seulement les dates principales)
        if p.sessions and len(p.sessions) > 0:
            # Utiliser les sessions
            for idx, session in enumerate(p.sessions):
                titre_session = p.titre
                if len(p.sessions) > 1:
                    titre_session += f" (Session {idx + 1}/{len(p.sessions)})"

                # Extraire les heures correctement
                heure_debut = session_presta.date_debut.strftime('%H:%M') if session_presta.date_debut else '00:00'
                heure_fin = session_presta.date_fin.strftime('%H:%M') if session_presta.date_fin else heure_debut

                # Pour les sessions multi-jours, créer un événement pour CHAQUE jour
                date_debut_session = session_presta.date_debut.date() if session_presta.date_debut else None
                date_fin_session = session_presta.date_fin.date() if session_presta.date_fin else date_debut_session

                if date_debut_session and date_fin_session:
                    # Créer un événement pour chaque jour de la période
                    date_courante = date_debut_session
                    while date_courante <= date_fin_session:
                        # Afficher l'heure uniquement pour le premier et dernier jour
                        if date_courante == date_debut_session:
                            heure_affichee = heure_debut
                        elif date_courante == date_fin_session and date_courante != date_debut_session:
                            heure_affichee = f"→ {heure_fin}"
                        else:
                            heure_affichee = "Journée"

                        events.append({
                            'id': p.id,
                            'session_id': session_presta.id,
                            'titre': titre_session,
                            'type_prestation': p.type_prestation,
                            'client_nom': client_nom,
                            'date_debut': date_courante.strftime('%Y-%m-%d'),
                            'date_fin': date_courante.strftime('%Y-%m-%d'),
                            'heure_debut': heure_affichee,
                            'heure_fin': heure_fin,
                            'color': color,
                            'allDay': session_presta.journee_complete or date_courante != date_debut_session
                        })
                        date_courante = date_courante + timedelta(days=1)
        else:
            # Fallback : si pas de sessions, utiliser les dates principales
            heure_debut = p.date_debut.strftime('%H:%M') if p.date_debut else '00:00'
            heure_fin = p.date_fin.strftime('%H:%M') if p.date_fin else heure_debut

            events.append({
                'id': p.id,
                'titre': p.titre,
                'type_prestation': p.type_prestation,
                'client_nom': client_nom,
                'date_debut': p.date_debut.strftime('%Y-%m-%d') if p.date_debut else '',
                'date_fin': p.date_fin.strftime('%Y-%m-%d') if p.date_fin else (p.date_debut.strftime('%Y-%m-%d') if p.date_debut else ''),
                'heure_debut': heure_debut,
                'heure_fin': heure_fin,
                'color': color,
                'allDay': p.journee_entiere
            })

    # 2. Ajouter les indisponibilités
    indisponibilites = Indisponibilite.query.order_by(Indisponibilite.date_debut).all()

    for indispo in indisponibilites:
        # Calculer toutes les dates de la période d'indisponibilité
        date_courante = indispo.date_debut
        while date_courante <= indispo.date_fin:
            events.append({
                'id': f'indispo-{indispo.id}-{date_courante.strftime("%Y%m%d")}',
                'titre': f'🚫 {indispo.motif}',
                'type_prestation': 'Indisponibilité',
                'client_nom': indispo.note or '',
                'date_debut': date_courante.strftime('%Y-%m-%d'),
                'date_fin': date_courante.strftime('%Y-%m-%d'),
                'heure_debut': 'Journée',
                'heure_fin': 'Journée',
                'color': '#D32F2F',  # Rouge foncé pour indisponibilité
                'allDay': True,
                'is_indisponibilite': True  # Flag pour distinguer des prestations
            })
            date_courante = date_courante + timedelta(days=1)

    return jsonify({'success': True, 'prestations': events})

@app.route('/api/rechercher-entreprise')
def api_rechercher_entreprise():
    """API pour rechercher une entreprise par nom"""
    query = request.args.get('q', '').strip()
    latitude = request.args.get('lat', type=float)
    longitude = request.args.get('lon', type=float)
    rayon = request.args.get('rayon', 10, type=int)
    debug_mode = request.args.get('debug', '').lower() == 'true'

    debug_info = {'etapes': []}
    debug_info['etapes'].append(f"Query initiale: '{query}'")

    if not query or len(query) < 3:
        return jsonify({'success': False, 'message': 'Requête trop courte (min 3 caractères)'})

    # Approche intelligente : essayer plusieurs stratégies
    ville_detectee = None
    nom_entreprise = query
    entreprises = []

    # STRATÉGIE 1 : Recherche directe avec Nominatim (ex: "leclerc carcassonne")
    debug_info['etapes'].append(f"Stratégie 1: Recherche directe Nominatim avec '{query}'")
    entreprises = rechercher_entreprises_nominatim_direct(query)
    debug_info['etapes'].append(f"Nominatim direct a trouvé: {len(entreprises)} entreprises")

    # STRATÉGIE 2 : Si rien trouvé, essayer de séparer nom/ville intelligemment
    if len(entreprises) == 0:
        parts = query.strip().split()
        if len(parts) >= 2:
            import requests
            
            # Essayer avec les 2 derniers mots comme ville (ex: "Saint Gaudens")
            # puis 1 seul mot si ça échoue
            for nb_mots_ville in [2, 1]:
                if len(parts) <= nb_mots_ville:
                    continue  # Pas assez de mots
                
                ville_potentielle = ' '.join(parts[-nb_mots_ville:])
                nom_potentiel = ' '.join(parts[:-nb_mots_ville])
                
                debug_info['etapes'].append(f"Strategie 2.{nb_mots_ville}: nom='{nom_potentiel}', ville='{ville_potentielle}'")
                
                # Essayer de géocoder cette ville
                try:
                    geocode_url = f"https://nominatim.openstreetmap.org/search?q={ville_potentielle},France&format=json&limit=1"
                    resp = requests.get(geocode_url, headers={'User-Agent': 'GestionEntreprise/1.0'}, timeout=5)
                    
                    if resp.status_code == 200 and resp.json():
                        geo_data = resp.json()[0]
                        latitude = float(geo_data['lat'])
                        longitude = float(geo_data['lon'])
                        ville_detectee = ville_potentielle
                        nom_entreprise = nom_potentiel
                        rayon = 20
                        debug_info['etapes'].append(f"Ville '{ville_potentielle}' geolocalisee: lat={latitude}, lon={longitude}")
                        
                        # Rechercher avec nom + ville séparés
                        entreprises = rechercher_entreprises_nominatim(nom_entreprise, ville_detectee)
                        debug_info['etapes'].append(f"Nominatim separe a trouve: {len(entreprises)} entreprises")
                        
                        # Si on a trouvé des résultats, sortir de la boucle
                        if len(entreprises) > 0:
                            break
                    else:
                        debug_info['etapes'].append(f"Geocodage de '{ville_potentielle}' echoue (pas de resultat)")
                
                except Exception as e:
                    debug_info['etapes'].append(f"Erreur geocodage '{ville_potentielle}': {str(e)}")

    # STRATÉGIE 3 : Si toujours rien et on a des coordonnées, essayer Overpass
    if len(entreprises) == 0 and latitude and longitude:
        debug_info['etapes'].append(f"Stratégie 3: Recherche Overpass autour de lat={latitude}, lon={longitude}, rayon={rayon}km")
        entreprises = rechercher_entreprises_overpass(nom_entreprise, latitude, longitude, rayon)
        debug_info['etapes'].append(f"Overpass a trouvé: {len(entreprises)} entreprises")

    debug_info['etapes'].append(f"Total d'entreprises trouvées: {len(entreprises)}")

    if debug_mode:
        return jsonify({'success': True, 'entreprises': entreprises, 'debug': debug_info})

    return jsonify({'success': True, 'entreprises': entreprises})

@app.route('/api/rechercher-zone')
def api_rechercher_zone():
    """API pour rechercher des entreprises dans une zone"""
    ville = request.args.get('ville', '')
    secteur = request.args.get('secteur', '')
    rayon = request.args.get('rayon', 20, type=int)

    if not ville:
        return jsonify({'success': False, 'message': 'Ville requise'})

    entreprises = rechercher_par_zone(ville, secteur if secteur else None, rayon)
    return jsonify({'success': True, 'entreprises': entreprises, 'count': len(entreprises)})

@app.route('/api/rechercher-clients')
def api_rechercher_clients():
    """API pour rechercher des clients existants"""
    query = request.args.get('q', '').strip()

    if not query or len(query) < 2:
        return jsonify({'success': False, 'message': 'Requête trop courte (min 2 caractères)'})

    # Rechercher dans nom, prénom et entreprise (n'importe où dans le texte)
    clients = Client.query.filter(
        Client.actif == True,
        db.or_(
            Client.nom.ilike(f'%{query}%'),
            Client.prenom.ilike(f'%{query}%'),
            Client.entreprise.ilike(f'%{query}%')
        )
    ).order_by(Client.nom).all()

    # Dédupliquer manuellement (car .distinct() ne fonctionne pas toujours avec db.or_())
    clients_uniques = {}
    for client in clients:
        if client.id not in clients_uniques:
            clients_uniques[client.id] = client

    # Limiter à 20 résultats
    clients_dedupliques = list(clients_uniques.values())[:20]

    # Convertir en JSON
    clients_data = []
    for client in clients_dedupliques:
        client_display = ''
        if client.prenom:
            client_display = f"{client.prenom} {client.nom}"
        else:
            client_display = client.nom

        # Ajouter l'entreprise uniquement si elle est différente du nom
        if client.entreprise and client.entreprise != client.nom:
            client_display += f" ({client.entreprise})"

        clients_data.append({
            'id': client.id,
            'nom': client.nom,
            'prenom': client.prenom,
            'entreprise': client.entreprise,
            'display': client_display,
            'email': client.email
        })

    return jsonify({'success': True, 'clients': clients_data})

@app.route('/api/demandeurs')
def api_demandeurs():
    """API pour récupérer la liste des demandeurs uniques (pour autocomplete)"""
    # Récupérer tous les demandeurs non vides de la base
    demandeurs_query = db.session_presta.query(Prestation.demandeur).filter(
        Prestation.demandeur.isnot(None),
        Prestation.demandeur != ''
    ).distinct().order_by(Prestation.demandeur).all()

    # Extraire les valeurs (query retourne des tuples)
    demandeurs = [d[0] for d in demandeurs_query if d[0] and d[0].strip()]

    return jsonify({'success': True, 'demandeurs': demandeurs})

# ============================================================================
# ROUTES STATISTIQUES
# ============================================================================

@app.route('/statistiques')
def statistiques():
    """Page statistiques avec graphiques"""
    # Statistiques par client (nombre de prestations)
    from sqlalchemy import func
    stats_clients_raw = db.session_presta.query(
        Client.nom,
        func.count(Prestation.id).label('nombre')
    ).join(Prestation).group_by(Client.id).order_by(func.count(Prestation.id).desc()).limit(10).all()

    # Convertir les Row en liste de tuples pour JSON serialization
    stats_clients = [(row[0], row[1]) for row in stats_clients_raw]

    # Statistiques par mois (prestations et CA) sur l'année en cours
    annee_en_cours = datetime.now().year
    stats_mois = []

    for mois in range(1, 13):
        debut_mois = datetime(annee_en_cours, mois, 1)
        if mois == 12:
            fin_mois = datetime(annee_en_cours + 1, 1, 1)
        else:
            fin_mois = datetime(annee_en_cours, mois + 1, 1)

        # Récupérer les prestations du mois
        prestations_mois = Prestation.query.filter(
            Prestation.date_debut >= debut_mois,
            Prestation.date_debut < fin_mois,
            Prestation.statut != 'Annulée'
        ).all()

        # Nombre de prestations du mois
        nb_prestations = len(prestations_mois)

        # CA du mois
        ca = sum(p.tarif_total or 0 for p in prestations_mois)

        # Statistiques logistiques du mois
        distance_mois = 0
        repas_mois = 0
        hebergements_mois = 0

        for p in prestations_mois:
            if p.distance_km:
                jours = 1
                if p.date_debut and p.date_fin:
                    delta = p.date_fin.date() - p.date_debut.date()
                    jours = max(1, delta.days + 1)
                distance_mois += p.distance_km * 2 * jours

            if p.nb_repas:
                repas_mois += p.nb_repas

            if p.nb_hebergements:
                hebergements_mois += p.nb_hebergements

        stats_mois.append({
            'mois': mois,
            'nom_mois': debut_mois.strftime('%B'),
            'nb_prestations': nb_prestations,
            'ca': float(ca),
            'distance_km': round(distance_mois, 1),
            'repas': repas_mois,
            'hebergements': hebergements_mois
        })

    # Statistiques logistiques sur l'année en cours
    prestations_annee = Prestation.query.filter(
        Prestation.date_debut >= datetime(annee_en_cours, 1, 1),
        Prestation.date_debut < datetime(annee_en_cours + 1, 1, 1),
        Prestation.statut != 'Annulée'
    ).all()

    # Calculer les totaux logistiques
    total_distance = 0
    total_repas = 0
    total_hebergements = 0
    nb_jours_formation = 0

    for p in prestations_annee:
        # Distance : calculer aller-retour par jour de formation
        if p.distance_km:
            # Calculer le nombre de jours de formation
            jours = 1  # Par défaut 1 jour
            if p.date_debut and p.date_fin:
                delta = p.date_fin.date() - p.date_debut.date()
                jours = max(1, delta.days + 1)  # +1 car inclus les deux bornes

            # Distance aller-retour = distance × 2 × nombre de jours
            total_distance += p.distance_km * 2 * jours
            nb_jours_formation += jours

        # Repas
        if p.nb_repas:
            total_repas += p.nb_repas

        # Hébergements
        if p.nb_hebergements:
            total_hebergements += p.nb_hebergements

    stats_logistique = {
        'total_distance_km': round(total_distance, 1),
        'total_repas': total_repas,
        'total_hebergements': total_hebergements,
        'nb_jours_formation': nb_jours_formation
    }

    return render_template('statistiques.html',
                         stats_clients=stats_clients,
                         stats_mois=stats_mois,
                         stats_logistique=stats_logistique,
                         annee=annee_en_cours)

# ============================================================================
# ROUTES COMPTABILITÉ
# ============================================================================

@app.route('/facture/<int:facture_id>')
def facture_detail(facture_id):
    """Afficher le détail d'une facture"""
    facture = Facture.query.get_or_404(facture_id)
    entreprise = Entreprise.query.first()

    # Calculer la date limite de paiement
    date_limite = None
    if facture.date_facture and facture.prestation and facture.prestation.client:
        delai = facture.prestation.client.delai_paiement_jours or 30
        date_limite = facture.date_facture + timedelta(days=delai)

    return render_template('facture_detail.html', facture=facture, entreprise=entreprise, date_limite=date_limite)

@app.route('/factures-en-cours')
def factures_en_cours():
    """Liste des factures en cours (envoyées mais non payées)"""
    factures = []
    total_factures_en_cours = 0

    try:
        factures_query = Facture.query.filter(Facture.date_envoi.isnot(None)).all()

        for facture in factures_query:
            # Vérifier si un paiement complet existe
            paiement_complet = Paiement.query.filter_by(
                facture_id=facture.id,
                statut='Payé'
            ).first()

            if not paiement_complet:
                factures.append(facture)
                total_factures_en_cours += facture.total_ttc or 0
    except:
        pass

    return render_template('factures_en_cours.html',
                         factures=factures,
                         total=total_factures_en_cours)

@app.route('/factures-en-retard')
def factures_en_retard():
    """Liste des factures en retard (date butoir dépassée)"""
    factures = []
    total_factures_retard = 0

    try:
        factures_query = Facture.query.all()

        for facture in factures_query:
            # Vérifier si un paiement complet existe
            paiement_complet = Paiement.query.filter_by(
                facture_id=facture.id,
                statut='Payé'
            ).first()

            if not paiement_complet and facture.date_facture and facture.prestation and facture.prestation.client:
                # Calculer la date butoir
                delai = facture.prestation.client.delai_paiement_jours or 30
                date_butoir = facture.date_facture + timedelta(days=delai)

                # Si aujourd'hui > date butoir, c'est en retard
                if datetime.now().date() > date_butoir:
                    facture.date_butoir = date_butoir  # Ajouter pour affichage
                    facture.jours_retard = (datetime.now().date() - date_butoir).days
                    factures.append(facture)
                    total_factures_retard += facture.total_ttc or 0
    except:
        pass

    return render_template('factures_en_retard.html',
                         factures=factures,
                         total=total_factures_retard)

@app.route('/paiements-en-retard')
def paiements_en_retard():
    """Liste des paiements en retard (date butoir dépassée)"""
    paiements = []
    total_paiements_retard = 0

    try:
        paiements_query = Paiement.query.filter(
            Paiement.statut.in_(['En attente', 'Partiel'])
        ).all()

        for paiement in paiements_query:
            if paiement.date_butoir and datetime.now().date() > paiement.date_butoir:
                # Calculer jours de retard
                paiement.jours_retard = (datetime.now().date() - paiement.date_butoir).days
                paiements.append(paiement)
                total_paiements_retard += (paiement.montant_total or 0) - (paiement.montant_paye or 0)
    except:
        pass

    return render_template('paiements_en_retard.html',
                         paiements=paiements,
                         total=total_paiements_retard)

@app.route('/paiements-recus')
def paiements_recus():
    """Liste des paiements reçus avec filtre de dates"""
    # Récupérer les paramètres de date (par défaut: 1er janvier de l'année en cours)
    date_debut_str = request.args.get('date_debut')
    date_fin_str = request.args.get('date_fin')

    # Dates par défaut
    if not date_debut_str:
        date_debut = datetime(datetime.now().year, 1, 1).date()
    else:
        date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()

    if not date_fin_str:
        date_fin = datetime.now().date()
    else:
        date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()

    # Récupérer les paiements payés dans la période
    paiements = []
    total_paiements_recus = 0

    try:
        paiements_query = Paiement.query.filter(
            Paiement.statut == 'Payé',
            Paiement.date_paiement.isnot(None),
            Paiement.date_paiement >= date_debut,
            Paiement.date_paiement <= date_fin
        ).order_by(Paiement.date_paiement.desc()).all()

        paiements = paiements_query
        total_paiements_recus = sum([p.montant_paye or 0 for p in paiements])
    except:
        pass

    return render_template('paiements_recus.html',
                         paiements=paiements,
                         total=total_paiements_recus,
                         date_debut=date_debut,
                         date_fin=date_fin)

# ============================================================================
# ROUTES SAISIE DEVIS, FACTURES, PAIEMENTS
# ============================================================================

@app.route('/devis/saisie/<int:prestation_id>', methods=['GET', 'POST'])
def devis_saisie(prestation_id):
    """Créer un devis pour une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)
    entreprise = Entreprise.query.first()

    if request.method == 'POST':
        # Générer référence devis automatiquement
        annee = datetime.now().year
        dernier_devis = Devis.query.filter(
            Devis.reference_devis.like(f'DE-{annee}-%')
        ).order_by(Devis.reference_devis.desc()).first()

        if dernier_devis:
            dernier_num = int(dernier_devis.reference_devis.split('-')[-1])
            nouveau_num = dernier_num + 1
        else:
            nouveau_num = 1

        reference_devis = f'DE-{annee}-{nouveau_num:03d}'

        # Créer le devis
        devis = Devis(
            prestation_id=prestation_id,
            reference_devis=reference_devis,
            date_devis=datetime.strptime(request.form.get('date_devis'), '%Y-%m-%d').date(),
            date_envoi=datetime.strptime(request.form.get('date_envoi'), '%Y-%m-%d').date() if request.form.get('date_envoi') else None,
            date_validite=datetime.strptime(request.form.get('date_validite'), '%Y-%m-%d').date() if request.form.get('date_validite') else None,
            mail_envoi=request.form.get('mail_envoi'),
            remise=float(request.form.get('remise', 0)),
            remise_ht=float(request.form.get('remise_ht', 0)),
            tva_applicable=float(request.form.get('tva_applicable', 0)),
            commentaire=request.form.get('commentaire')
        )

        db.session_presta.add(devis)
        db.session_presta.flush()  # Obtenir l'ID du devis

        # Traiter les lignes de déplacement
        codes_dep = request.form.getlist('deplacement_code[]')
        types_dep = request.form.getlist('deplacement_type[]')
        nbres_dep = request.form.getlist('deplacement_nbre[]')
        pus_dep = request.form.getlist('deplacement_pu_ht[]')
        pts_dep = request.form.getlist('deplacement_pt_ht[]')

        total_deplacement = 0
        for i in range(len(codes_dep)):
            if types_dep[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneDevisDeplacement(
                    devis_id=devis.id,
                    code=codes_dep[i].strip() or None,
                    type=types_dep[i].strip(),
                    nbre=float(nbres_dep[i]) if nbres_dep[i] else 0,
                    pu_ht=float(pus_dep[i]) if pus_dep[i] else 0,
                    pt_ht=float(pts_dep[i]) if pts_dep[i] else 0
                )
                db.session_presta.add(ligne)
                total_deplacement += ligne.pt_ht

        # Traiter les lignes de fourniture
        codes_four = request.form.getlist('fourniture_code[]')
        types_four = request.form.getlist('fourniture_type[]')
        nbres_four = request.form.getlist('fourniture_nbre[]')
        pus_four = request.form.getlist('fourniture_pu_ht[]')
        pts_four = request.form.getlist('fourniture_pt_ht[]')

        total_fourniture = 0
        for i in range(len(codes_four)):
            if types_four[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneDevisFourniture(
                    devis_id=devis.id,
                    code=codes_four[i].strip() or None,
                    type=types_four[i].strip(),
                    nbre=float(nbres_four[i]) if nbres_four[i] else 0,
                    pu_ht=float(pus_four[i]) if pus_four[i] else 0,
                    pt_ht=float(pts_four[i]) if pts_four[i] else 0
                )
                db.session_presta.add(ligne)
                total_fourniture += ligne.pt_ht

        # Traiter les lignes de prestation
        codes_prest = request.form.getlist('prestation_code[]')
        types_prest = request.form.getlist('prestation_type[]')
        nbres_prest = request.form.getlist('prestation_nbre[]')
        pus_prest = request.form.getlist('prestation_pu_ht[]')
        pts_prest = request.form.getlist('prestation_pt_ht[]')

        total_prestation = 0
        for i in range(len(codes_prest)):
            if types_prest[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneDevisPrestation(
                    devis_id=devis.id,
                    code=codes_prest[i].strip() or None,
                    type=types_prest[i].strip(),
                    nbre=float(nbres_prest[i]) if nbres_prest[i] else 0,
                    pu_ht=float(pus_prest[i]) if pus_prest[i] else 0,
                    pt_ht=float(pts_prest[i]) if pts_prest[i] else 0
                )
                db.session_presta.add(ligne)
                total_prestation += ligne.pt_ht

        # Mettre à jour les totaux globaux dans le devis (pour compatibilité)
        devis.deplacement_prix_ht = total_deplacement
        devis.fourniture_prix_ht = total_fourniture
        devis.prestation_prix_ht = total_prestation

        # Calculer totaux
        total_ht = total_deplacement + total_fourniture + total_prestation - devis.remise_ht
        devis.total_prix_ht = total_ht
        devis.total_ttc = total_ht * (1 + devis.tva_applicable / 100)

        # Mettre à jour le statut devis de la prestation
        if devis.date_envoi:
            prestation.statut_devis = 'Envoyé'
        else:
            prestation.statut_devis = 'Non envoyé'

        db.session_presta.commit()

        flash('Devis créé avec succès !', 'success')
        return redirect(url_for('prestation_detail', prestation_id=prestation_id))

    return render_template('devis_saisie.html', prestation=prestation, entreprise=entreprise)

@app.route('/facture/saisie/<int:prestation_id>', methods=['GET', 'POST'])
def facture_saisie(prestation_id):
    """Créer ou modifier une facture pour une prestation"""
    prestation = Prestation.query.get_or_404(prestation_id)
    entreprise = Entreprise.query.first()

    # Récupérer le paramètre pour savoir si on doit créer une nouvelle facture
    creer_nouvelle = request.args.get('nouvelle', 'non')

    # Vérifier si une facture existe déjà pour cette prestation
    facture_existante = Facture.query.filter_by(prestation_id=prestation_id).first()

    # Variable pour stocker la facture créée/modifiée
    facture_actuelle = None

    if request.method == 'POST':
        action = request.form.get('action', 'creer')

        # Si on modifie une facture existante
        if action == 'modifier' and facture_existante:
            facture = facture_existante
            # On garde la même référence
        else:
            # Générer une nouvelle référence facture
            annee = datetime.now().year
            mois = datetime.now().month
            derniere_facture = Facture.query.filter(
                Facture.reference_facture.like(f'FA-{annee}-{mois:02d}-%')
            ).order_by(Facture.reference_facture.desc()).first()

            if derniere_facture:
                dernier_num = int(derniere_facture.reference_facture.split('-')[-1])
                nouveau_num = dernier_num + 1
            else:
                nouveau_num = 1

            reference_facture = f'FA-{annee}-{mois:02d}-{nouveau_num:03d}'

            # Créer une nouvelle facture
            facture = Facture(
                prestation_id=prestation_id,
                reference_facture=reference_facture
            )

        # Mettre à jour les données de la facture
        facture.date_facture = datetime.strptime(request.form.get('date_facture'), '%Y-%m-%d').date()
        facture.date_envoi = datetime.strptime(request.form.get('date_envoi'), '%Y-%m-%d').date() if request.form.get('date_envoi') else None
        facture.mail_envoi = request.form.get('mail_envoi')
        facture.acompte_prix_ht = float(request.form.get('acompte_prix_ht', 0))
        facture.remise = float(request.form.get('remise', 0))
        facture.majoration = float(request.form.get('majoration', 0))
        facture.remise_ht = float(request.form.get('remise_ht', 0))
        facture.tva_applicable = float(request.form.get('tva_applicable', 0))
        facture.commentaire = request.form.get('commentaire')
        facture.rib = request.form.get('rib')

        # Supprimer les anciennes lignes si on modifie une facture existante
        if action == 'modifier':
            LigneFactureDeplacement.query.filter_by(facture_id=facture.id).delete()
            LigneFactureFourniture.query.filter_by(facture_id=facture.id).delete()
            LigneFacturePrestation.query.filter_by(facture_id=facture.id).delete()

        # Sauvegarder la facture pour obtenir un ID si c'est une nouvelle facture
        if action != 'modifier':
            db.session_presta.add(facture)
            db.session_presta.flush()  # Obtenir l'ID de la facture

        # Traiter les lignes de déplacement
        codes_dep = request.form.getlist('deplacement_code[]')
        types_dep = request.form.getlist('deplacement_type[]')
        nbres_dep = request.form.getlist('deplacement_nbre[]')
        pus_dep = request.form.getlist('deplacement_pu_ht[]')
        pts_dep = request.form.getlist('deplacement_pt_ht[]')

        total_deplacement = 0
        for i in range(len(codes_dep)):
            if types_dep[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneFactureDeplacement(
                    facture_id=facture.id,
                    code=codes_dep[i].strip() or None,
                    type=types_dep[i].strip(),
                    nbre=float(nbres_dep[i]) if nbres_dep[i] else 0,
                    pu_ht=float(pus_dep[i]) if pus_dep[i] else 0,
                    pt_ht=float(pts_dep[i]) if pts_dep[i] else 0
                )
                db.session_presta.add(ligne)
                total_deplacement += ligne.pt_ht

        # Traiter les lignes de fourniture
        codes_four = request.form.getlist('fourniture_code[]')
        types_four = request.form.getlist('fourniture_type[]')
        nbres_four = request.form.getlist('fourniture_nbre[]')
        pus_four = request.form.getlist('fourniture_pu_ht[]')
        pts_four = request.form.getlist('fourniture_pt_ht[]')

        total_fourniture = 0
        for i in range(len(codes_four)):
            if types_four[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneFactureFourniture(
                    facture_id=facture.id,
                    code=codes_four[i].strip() or None,
                    type=types_four[i].strip(),
                    nbre=float(nbres_four[i]) if nbres_four[i] else 0,
                    pu_ht=float(pus_four[i]) if pus_four[i] else 0,
                    pt_ht=float(pts_four[i]) if pts_four[i] else 0
                )
                db.session_presta.add(ligne)
                total_fourniture += ligne.pt_ht

        # Traiter les lignes de prestation
        codes_prest = request.form.getlist('prestation_code[]')
        types_prest = request.form.getlist('prestation_type[]')
        nbres_prest = request.form.getlist('prestation_nbre[]')
        pus_prest = request.form.getlist('prestation_pu_ht[]')
        pts_prest = request.form.getlist('prestation_pt_ht[]')

        total_prestation = 0
        for i in range(len(codes_prest)):
            if types_prest[i].strip():  # Ne créer que si le type n'est pas vide
                ligne = LigneFacturePrestation(
                    facture_id=facture.id,
                    code=codes_prest[i].strip() or None,
                    type=types_prest[i].strip(),
                    nbre=float(nbres_prest[i]) if nbres_prest[i] else 0,
                    pu_ht=float(pus_prest[i]) if pus_prest[i] else 0,
                    pt_ht=float(pts_prest[i]) if pts_prest[i] else 0
                )
                db.session_presta.add(ligne)
                total_prestation += ligne.pt_ht

        # Mettre à jour les totaux globaux dans la facture (pour compatibilité)
        facture.deplacement_prix_ht = total_deplacement
        facture.fourniture_prix_ht = total_fourniture
        facture.prestation_prix_ht = total_prestation

        # Calculer totaux
        total_ht = total_deplacement + total_fourniture + total_prestation - facture.acompte_prix_ht - facture.remise_ht + facture.majoration
        facture.total_prix_ht = total_ht
        facture.total_ttc = total_ht * (1 + facture.tva_applicable / 100)

        # Mettre à jour le statut facture de la prestation
        if facture.date_envoi:
            prestation.statut_facture = 'Envoyée'

            # Envoyer l'email si demandé
            if request.form.get('envoyer_email') == 'oui' and facture.mail_envoi and entreprise:
                try:
                    # Utiliser les paramètres email de l'entreprise
                    if entreprise.email_smtp_host and entreprise.email_smtp_user:
                        import smtplib
                        from email.mime.text import MIMEText

                        corps = f"""Bonjour,

Veuillez trouver ci-joint la facture {facture.reference_facture} d'un montant de {facture.total_prix_ht:.2f} € HT.

Cordialement,
{entreprise.nom}"""

                        # Créer un message simple avec encodage UTF-8
                        msg = MIMEText(corps, 'plain', 'utf-8')
                        msg['Subject'] = f'Facture {facture.reference_facture}'
                        msg['From'] = entreprise.email_smtp_user
                        msg['To'] = facture.mail_envoi
                        # Ajouter une copie cachée à l'expéditeur
                        msg['Bcc'] = entreprise.email_smtp_user

                        # Utiliser SMTP_SSL pour le port 465 (IONOS) ou SMTP avec STARTTLS pour le port 587
                        port = entreprise.email_smtp_port or 587
                        if port == 465:
                            # Port 465 : SSL direct dès la connexion (IONOS, etc.)
                            server = smtplib.SMTP_SSL(entreprise.email_smtp_host, port, timeout=60)
                        else:
                            # Port 587 : STARTTLS (Gmail, Outlook, etc.)
                            server = smtplib.SMTP(entreprise.email_smtp_host, port, timeout=60)
                            server.starttls()

                        server.login(entreprise.email_smtp_user, entreprise.email_smtp_password)
                        server.send_message(msg)
                        server.quit()

                        flash('Facture créée et email envoyé avec succès !', 'success')
                except Exception as e:
                    flash(f'Facture créée mais erreur lors de l\'envoi de l\'email : {str(e)}', 'warning')
        else:
            prestation.statut_facture = 'Non envoyée'

        # Créer automatiquement un paiement associé si facture envoyée
        if facture.date_envoi and action != 'modifier':
            dernier_paiement = Paiement.query.order_by(Paiement.numero_paiement.desc()).first()
            if dernier_paiement and dernier_paiement.numero_paiement:
                dernier_num = int(dernier_paiement.numero_paiement.split('-')[1])
                nouveau_num = dernier_num + 1
            else:
                nouveau_num = 1

            numero_paiement = f'P-{nouveau_num:04d}'
            delai = prestation.client.delai_paiement_jours if prestation.client else 30
            date_butoir = facture.date_facture + timedelta(days=delai)

            paiement = Paiement(
                facture_id=facture.id,
                prestation_id=prestation_id,
                numero_paiement=numero_paiement,
                numero_facture=facture.reference_facture,
                date_butoir=date_butoir,
                montant_total=facture.total_ttc,
                montant_paye=0,
                statut='En attente'
            )
            db.session_presta.add(paiement)
            prestation.statut_paiement = 'En attente'

        db.session_presta.commit()
        facture_actuelle = facture

       
        # Rester sur la page de saisie avec la facture créée
        return redirect(url_for('facture_saisie', prestation_id=prestation_id, facture_id=facture.id))

    # GET : Charger la facture existante ou préparer une nouvelle
    facture_id = request.args.get('facture_id', type=int)
    if facture_id:
        facture_actuelle = Facture.query.get(facture_id)
    elif facture_existante and creer_nouvelle == 'non':
        facture_actuelle = facture_existante

    return render_template('facture_saisie.html',
                         prestation=prestation,
                         entreprise=entreprise,
                         facture=facture_actuelle,
                         facture_existante=facture_existante)

@app.route('/paiement/saisie', methods=['GET', 'POST'])
def paiement_saisie():
    """Enregistrer un paiement"""
    facture_id = request.args.get('facture_id', type=int)
    paiement_id = request.args.get('paiement_id', type=int)
    prestation_id = request.args.get('prestation_id', type=int)

    facture = None
    paiement = None
    date_butoir_calculee = None

    # Si on vient avec un prestation_id, chercher la facture associée
    if prestation_id and not facture_id:
        facture = Facture.query.filter_by(prestation_id=prestation_id).first()
        if facture:
            facture_id = facture.id

    if facture_id:
        facture = Facture.query.get_or_404(facture_id)
        # Chercher si un paiement existe déjà
        paiement = Paiement.query.filter_by(facture_id=facture_id).first()

        # Calculer la date butoir si pas de paiement existant
        if not paiement and facture.date_facture and facture.prestation and facture.prestation.client:
            delai = facture.prestation.client.delai_paiement_jours or 30
            date_butoir_calculee = facture.date_facture + timedelta(days=delai)

    elif paiement_id:
        paiement = Paiement.query.get_or_404(paiement_id)
        facture = paiement.facture

    if request.method == 'POST':
        if not paiement:
            # Créer nouveau paiement
            dernier_paiement = Paiement.query.order_by(Paiement.numero_paiement.desc()).first()
            if dernier_paiement and dernier_paiement.numero_paiement:
                dernier_num = int(dernier_paiement.numero_paiement.split('-')[1])
                nouveau_num = dernier_num + 1
            else:
                nouveau_num = 1

            paiement = Paiement(
                facture_id=facture.id,
                prestation_id=facture.prestation_id,
                numero_paiement=f'P-{nouveau_num:04d}',
                numero_facture=facture.reference_facture
            )
            db.session_presta.add(paiement)

        # Mettre à jour les informations
        paiement.date_paiement = datetime.strptime(request.form.get('date_paiement'), '%Y-%m-%d').date() if request.form.get('date_paiement') else None
        paiement.mode_paiement = request.form.get('mode_paiement')
        paiement.montant_paye = float(request.form.get('montant_paye', 0))
        paiement.montant_total = float(request.form.get('montant_total', 0))
        paiement.notes = request.form.get('notes')

        # Calculer date butoir si pas déjà définie
        if not paiement.date_butoir and facture.date_facture and facture.prestation and facture.prestation.client:
            delai = facture.prestation.client.delai_paiement_jours or 30
            paiement.date_butoir = facture.date_facture + timedelta(days=delai)

        # Calculer jours de retard
        if paiement.date_butoir:
            if paiement.date_paiement:
                paiement.nb_jours_retard = max(0, (paiement.date_paiement - paiement.date_butoir).days)
            else:
                paiement.nb_jours_retard = max(0, (datetime.now().date() - paiement.date_butoir).days)

        # Définir statut
        if paiement.montant_paye >= paiement.montant_total:
            paiement.statut = 'Payé'
            facture.prestation.statut_paiement = 'Payé'
            facture.prestation.statut_facture = 'Payée'
        elif paiement.montant_paye > 0:
            paiement.statut = 'Partiel'
            facture.prestation.statut_paiement = 'Partiel'
        else:
            if paiement.date_butoir and datetime.now().date() > paiement.date_butoir:
                paiement.statut = 'En retard'
                facture.prestation.statut_paiement = 'En retard'
            else:
                paiement.statut = 'En attente'
                facture.prestation.statut_paiement = 'En attente'

        db.session_presta.commit()

        flash('Paiement enregistré avec succès !', 'success')
        return redirect(url_for('prestation_detail', prestation_id=facture.prestation_id))

    return render_template('paiement_saisie.html', facture=facture, paiement=paiement, date_butoir_calculee=date_butoir_calculee)

# ============================================================================
# ROUTES DOCUMENTS
# ============================================================================

@app.route('/prestation/<int:prestation_id>/document/upload', methods=['POST'])
def document_upload(prestation_id):
    """Upload un document"""
    prestation = Prestation.query.get_or_404(prestation_id)

    if 'fichier' not in request.files:
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('prestation_detail', prestation_id=prestation_id))

    fichier = request.files['fichier']

    if fichier.filename == '':
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('prestation_detail', prestation_id=prestation_id))

    # Sauvegarder le fichier
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    nom_fichier = f"{timestamp}_{fichier.filename}"
    chemin_fichier = os.path.join(app.config['UPLOAD_FOLDER'], nom_fichier)
    fichier.save(chemin_fichier)

    # Créer l'entrée dans la base
    document = Document(
        prestation_id=prestation_id,
        nom_fichier=nom_fichier,
        nom_original=fichier.filename,
        type_document=request.form.get('type_document', 'Autre'),
        chemin_fichier=chemin_fichier,
        taille_octets=os.path.getsize(chemin_fichier),
        notes=request.form.get('notes')
    )

    db.session_presta.add(document)
    db.session_presta.commit()

    flash('Document uploadé avec succès !', 'success')
    return redirect(url_for('prestation_detail', prestation_id=prestation_id))

@app.route('/document/<int:document_id>/telecharger')
def document_telecharger(document_id):
    """Télécharger un document"""
    document = Document.query.get_or_404(document_id)
    return send_file(document.chemin_fichier, as_attachment=True, download_name=document.nom_original)

@app.route('/document/<int:document_id>/supprimer', methods=['POST'])
def document_supprimer(document_id):
    """Supprimer un document"""
    document = Document.query.get_or_404(document_id)
    prestation_id = document.prestation_id

    # Supprimer le fichier physique
    if os.path.exists(document.chemin_fichier):
        os.remove(document.chemin_fichier)

    # Supprimer l'entrée de la base
    db.session_presta.delete(document)
    db.session_presta.commit()

    flash('Document supprimé avec succès !', 'success')
    return redirect(url_for('prestation_detail', prestation_id=prestation_id))

# ============================================================================
# ROUTES ENTREPRISE
# ============================================================================

@app.route('/entreprise')
def entreprise():
    """Afficher et gérer les informations de l'entreprise"""
    # Il ne devrait y avoir qu'une seule entrée entreprise
    info_entreprise = Entreprise.query.first()
    return render_template('entreprise.html', entreprise=info_entreprise)

@app.route('/entreprise/modifier', methods=['GET', 'POST'])
def entreprise_modifier():
    """Modifier les informations de l'entreprise"""
    info_entreprise = Entreprise.query.first()

    if request.method == 'POST':
        if info_entreprise:
            # Modifier l'entrée existante
            info_entreprise.nom = request.form['nom']
            info_entreprise.siret = request.form.get('siret')
            info_entreprise.adresse = request.form['adresse']
            info_entreprise.code_postal = request.form.get('code_postal')
            info_entreprise.ville = request.form.get('ville')
            info_entreprise.telephone = request.form.get('telephone')
            info_entreprise.email = request.form.get('email')
            info_entreprise.site_web = request.form.get('site_web')
            info_entreprise.notes = request.form.get('notes')

            # Configuration notifications
            info_entreprise.notif_actives = 'notif_actives' in request.form
            info_entreprise.email_smtp_host = request.form.get('email_smtp_host')
            info_entreprise.email_smtp_port = int(request.form.get('email_smtp_port', 587))
            info_entreprise.email_smtp_user = request.form.get('email_smtp_user')
            info_entreprise.email_smtp_password = request.form.get('email_smtp_password')
            info_entreprise.sms_actif = 'sms_actif' in request.form
            info_entreprise.sms_service = request.form.get('sms_service')
            info_entreprise.sms_api_key = request.form.get('sms_api_key')
            info_entreprise.sms_api_secret = request.form.get('sms_api_secret')
            info_entreprise.sms_from_number = request.form.get('sms_from_number')

            # Informations juridiques et bancaires
            info_entreprise.statut_juridique = request.form.get('statut_juridique')
            info_entreprise.capital = float(request.form['capital']) if request.form.get('capital') else None
            info_entreprise.numero_nda = request.form.get('numero_nda')
            info_entreprise.rcs = request.form.get('rcs')
            info_entreprise.domiciliation_bancaire = request.form.get('domiciliation_bancaire')
            info_entreprise.iban = request.form.get('iban')
            info_entreprise.bic = request.form.get('bic')

            info_entreprise.date_modification = datetime.utcnow()

            flash('Informations de l\'entreprise modifiées avec succès !', 'success')
        else:
            # Créer une nouvelle entrée
            info_entreprise = Entreprise(
                nom=request.form['nom'],
                siret=request.form.get('siret'),
                adresse=request.form['adresse'],
                code_postal=request.form.get('code_postal'),
                ville=request.form.get('ville'),
                telephone=request.form.get('telephone'),
                email=request.form.get('email'),
                site_web=request.form.get('site_web'),
                notes=request.form.get('notes'),
                # Configuration notifications
                notif_actives='notif_actives' in request.form,
                email_smtp_host=request.form.get('email_smtp_host'),
                email_smtp_port=int(request.form.get('email_smtp_port', 587)),
                email_smtp_user=request.form.get('email_smtp_user'),
                email_smtp_password=request.form.get('email_smtp_password'),
                sms_actif='sms_actif' in request.form,
                sms_service=request.form.get('sms_service'),
                sms_api_key=request.form.get('sms_api_key'),
                sms_api_secret=request.form.get('sms_api_secret'),
                sms_from_number=request.form.get('sms_from_number'),
                # Informations juridiques et bancaires
                statut_juridique=request.form.get('statut_juridique'),
                capital=float(request.form['capital']) if request.form.get('capital') else None,
                numero_nda=request.form.get('numero_nda'),
                rcs=request.form.get('rcs'),
                domiciliation_bancaire=request.form.get('domiciliation_bancaire'),
                iban=request.form.get('iban'),
                bic=request.form.get('bic')
            )
            db.session_presta.add(info_entreprise)
            flash('Informations de l\'entreprise créées avec succès !', 'success')

        db.session_presta.commit()
        return redirect(url_for('entreprise'))

    return render_template('entreprise_form.html', entreprise=info_entreprise)

@app.route('/api/entreprise/adresse')
def api_entreprise_adresse():
    """API pour récupérer l'adresse de l'entreprise (pour calcul d'itinéraire)"""
    info_entreprise = Entreprise.query.first()
    if info_entreprise:
        adresse_complete = f"{info_entreprise.adresse}, {info_entreprise.code_postal} {info_entreprise.ville}"
        return jsonify({
            'success': True,
            'adresse': adresse_complete,
            'adresse_brut': info_entreprise.adresse,
            'code_postal': info_entreprise.code_postal,
            'ville': info_entreprise.ville
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Aucune adresse d\'entreprise configurée'
        })

# ============================================================================
# ROUTES SAUVEGARDE / RESTAURATION
# ============================================================================

@app.route('/sauvegarde/creer')
def sauvegarde_creer():
    """Créer une sauvegarde de la base de données"""
    try:
        # Générer le nom du fichier avec timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')
        nom_fichier = f"gestion_entreprise_{timestamp}.db"

        # Chemins de sauvegarde
        chemin_local = os.path.join(app.config['BACKUP_FOLDER'], nom_fichier)
        chemin_gdrive = os.path.join(app.config['GDRIVE_BACKUP_PATH'], nom_fichier)

        # Copier la base de données locale
        # Obtenir le chemin absolu de la base de données depuis l'instance Flask
        db_source = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise.db')
        if os.path.exists(db_source):
            shutil.copy2(db_source, chemin_local)
            taille = os.path.getsize(chemin_local)

            # Tenter la copie vers Google Drive
            statut_gdrive = 'N/A'
            chemin_gdrive_final = None

            try:
                # Créer le dossier Google Drive s'il n'existe pas
                os.makedirs(app.config['GDRIVE_BACKUP_PATH'], exist_ok=True)
                shutil.copy2(chemin_local, chemin_gdrive)
                statut_gdrive = 'Success'
                chemin_gdrive_final = chemin_gdrive
            except Exception as e:
                statut_gdrive = 'Failed'
                flash(f'⚠️ Sauvegarde locale OK, mais échec Google Drive: {str(e)}', 'warning')

            # Copier également le dossier uploads s'il existe
            try:
                if os.path.exists('uploads') and os.listdir('uploads'):
                    uploads_backup_local = os.path.join(app.config['BACKUP_FOLDER'], f'uploads_{timestamp}')
                    shutil.copytree('uploads', uploads_backup_local, dirs_exist_ok=True)

                    if statut_gdrive == 'Success':
                        uploads_backup_gdrive = os.path.join(app.config['GDRIVE_BACKUP_PATH'], f'uploads_{timestamp}')
                        shutil.copytree('uploads', uploads_backup_gdrive, dirs_exist_ok=True)
            except Exception as e:
                print(f"Erreur lors de la copie des uploads: {e}")

            # Enregistrer la sauvegarde dans la base
            sauvegarde = Sauvegarde(
                nom_fichier=nom_fichier,
                taille_octets=taille,
                chemin_local=chemin_local,
                chemin_gdrive=chemin_gdrive_final,
                statut_gdrive=statut_gdrive
            )
            db.session_presta.add(sauvegarde)
            db.session_presta.commit()

            if statut_gdrive == 'Success':
                flash(f'✓ Sauvegarde créée avec succès ! (Local + Google Drive)', 'success')
            else:
                flash(f'✓ Sauvegarde locale créée avec succès !', 'success')
        else:
            flash('❌ Base de données introuvable !', 'error')

    except Exception as e:
        flash(f'❌ Erreur lors de la sauvegarde : {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/sauvegarde/liste')
def sauvegarde_liste():
    """Afficher la liste des sauvegardes disponibles"""
    # Récupérer les sauvegardes depuis la base de données
    sauvegardes_db = Sauvegarde.query.order_by(Sauvegarde.date_sauvegarde.desc()).all()

    # Lister aussi les fichiers physiques dans le dossier Sauvegardes
    sauvegardes_fichiers = []
    if os.path.exists(app.config['BACKUP_FOLDER']):
        for fichier in os.listdir(app.config['BACKUP_FOLDER']):
            if fichier.endswith('.db'):
                chemin_complet = os.path.join(app.config['BACKUP_FOLDER'], fichier)
                sauvegardes_fichiers.append({
                    'nom': fichier,
                    'chemin': chemin_complet,
                    'taille': os.path.getsize(chemin_complet),
                    'date': datetime.fromtimestamp(os.path.getmtime(chemin_complet))
                })

    return render_template('sauvegarde_liste.html',
                         sauvegardes_db=sauvegardes_db,
                         sauvegardes_fichiers=sauvegardes_fichiers)

@app.route('/sauvegarde/restaurer/<int:sauvegarde_id>')
def sauvegarde_restaurer(sauvegarde_id):
    """Restaurer une sauvegarde"""
    try:
        sauvegarde = Sauvegarde.query.get_or_404(sauvegarde_id)

        # Vérifier que le fichier existe
        if not os.path.exists(sauvegarde.chemin_local):
            flash('❌ Fichier de sauvegarde introuvable !', 'error')
            return redirect(url_for('sauvegarde_liste'))

        # Faire une sauvegarde de la base actuelle avant de restaurer
        db_actuelle = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise.db')
        db_backup_old = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise_OLD.db')

        if os.path.exists(db_actuelle):
            shutil.copy2(db_actuelle, db_backup_old)

        # Restaurer la sauvegarde
        shutil.copy2(sauvegarde.chemin_local, db_actuelle)

        flash(f'✓ Base de données restaurée avec succès ! (Ancienne base sauvegardée dans {db_backup_old})', 'success')

    except Exception as e:
        flash(f'❌ Erreur lors de la restauration : {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/sauvegarde/restaurer-fichier', methods=['POST'])
def sauvegarde_restaurer_fichier():
    """Restaurer une sauvegarde à partir d'un nom de fichier"""
    try:
        nom_fichier = request.form.get('nom_fichier')
        chemin_sauvegarde = os.path.join(app.config['BACKUP_FOLDER'], nom_fichier)

        # Vérifier que le fichier existe
        if not os.path.exists(chemin_sauvegarde):
            flash('❌ Fichier de sauvegarde introuvable !', 'error')
            return redirect(url_for('sauvegarde_liste'))

        # Faire une sauvegarde de la base actuelle avant de restaurer
        db_actuelle = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise.db')
        db_backup_old = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise_OLD.db')

        if os.path.exists(db_actuelle):
            shutil.copy2(db_actuelle, db_backup_old)

        # Restaurer la sauvegarde
        shutil.copy2(chemin_sauvegarde, db_actuelle)

        flash(f'✓ Base de données restaurée avec succès ! (Ancienne base sauvegardée dans {db_backup_old})', 'success')

    except Exception as e:
        flash(f'❌ Erreur lors de la restauration : {str(e)}', 'error')

    return redirect(url_for('index'))

# ============================================================================
# FONCTIONS NOTIFICATIONS
# ============================================================================

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def envoyer_email(destinataire_email, sujet, contenu_html):
    """
    Envoyer un email via SMTP
    Retourne (success: bool, message: str)
    """
    try:
        # Récupérer la configuration SMTP de l'entreprise
        entreprise = Entreprise.query.first()
        if not entreprise or not entreprise.notif_actives:
            return False, "Notifications non activées"

        if not entreprise.email_smtp_host or not entreprise.email_smtp_user:
            return False, "Configuration SMTP incomplète"

        # Créer le message
        msg = MIMEMultipart('alternative')
        msg['From'] = entreprise.email_smtp_user
        msg['To'] = destinataire_email
        msg['Subject'] = sujet

        # Ajouter le contenu HTML
        partie_html = MIMEText(contenu_html, 'html', 'utf-8')
        msg.attach(partie_html)

        # Se connecter au serveur SMTP et envoyer
        with smtplib.SMTP(entreprise.email_smtp_host, entreprise.email_smtp_port) as server:
            server.starttls()  # Sécuriser la connexion
        from cryptography.fernet import Fernet
        password_decrypted = decrypt_password(entreprise.email_smtp_password)
        server.login(entreprise.email_smtp_user, password_decrypted)
            server.send_message(msg)

        return True, "Email envoyé avec succès"

    except Exception as e:
        return False, f"Erreur SMTP: {str(e)}"


def envoyer_sms(destinataire_tel, message):
    """
    Envoyer un SMS via l'API configurée (Twilio, SMS Mode, OVH)
    Retourne (success: bool, message: str)
    """
    try:
        # Récupérer la configuration SMS de l'entreprise
        entreprise = Entreprise.query.first()
        if not entreprise or not entreprise.sms_actif:
            return False, "SMS non activé"

        if not entreprise.sms_service or not entreprise.sms_api_key:
            return False, "Configuration SMS incomplète"

        # Envoi selon le service configuré
        if entreprise.sms_service == 'twilio':
            return envoyer_sms_twilio(
                destinataire_tel,
                message,
                entreprise.sms_api_key,
                entreprise.sms_api_secret,
                entreprise.sms_from_number
            )
        elif entreprise.sms_service == 'smsmode':
            return envoyer_sms_smsmode(
                destinataire_tel,
                message,
                entreprise.sms_api_key
            )
        elif entreprise.sms_service == 'ovh':
            return envoyer_sms_ovh(
                destinataire_tel,
                message,
                entreprise.sms_api_key,
                entreprise.sms_api_secret
            )
        else:
            return False, f"Service SMS '{entreprise.sms_service}' non supporté"

    except Exception as e:
        return False, f"Erreur SMS: {str(e)}"


def envoyer_sms_twilio(destinataire_tel, message, account_sid, auth_token, from_number):
    """Envoyer un SMS via Twilio"""
    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            from_=from_number,
            to=destinataire_tel
        )

        return True, f"SMS Twilio envoyé (SID: {message.sid})"
    except ImportError:
        return False, "Module 'twilio' non installé. Installez-le avec: pip install twilio"
    except Exception as e:
        return False, f"Erreur Twilio: {str(e)}"


def envoyer_sms_smsmode(destinataire_tel, message, api_key):
    """Envoyer un SMS via SMS Mode (API HTTP)"""
    try:
        import requests

        url = "https://api.smsmode.com/http/1.6/sendSMS.do"
        params = {
            'accessToken': api_key,
            'message': message,
            'numero': destinataire_tel,
            'emetteur': 'MonEntreprise'  # Max 11 caractères
        }

        response = requests.get(url, params=params)

        if response.status_code == 200:
            return True, "SMS Mode envoyé avec succès"
        else:
            return False, f"Erreur SMS Mode: {response.text}"
    except Exception as e:
        return False, f"Erreur SMS Mode: {str(e)}"


def envoyer_sms_ovh(destinataire_tel, message, app_key, app_secret):
    """Envoyer un SMS via OVH (nécessite configuration avancée)"""
    return False, "Service OVH SMS non encore implémenté"


def creer_notification(type_notif, prestation_id, canal='email'):
    """
    Créer et envoyer une notification
    type_notif: 'rappel_prestation', 'facture_non_envoyee', 'facture_non_payee'
    """
    try:
        prestation = Prestation.query.get(prestation_id)
        if not prestation:
            return False, "Prestation introuvable"

        client = prestation.client
        if not client:
            return False, "Client introuvable"

        # Récupérer les infos de l'entreprise
        entreprise = Entreprise.query.first()

        # Préparer le contenu selon le type de notification
        if type_notif == 'rappel_prestation':
            # RAPPEL POUR L'ENTREPRISE (pas pour le client!)
            sujet = f"Rappel : Intervention demain - {client.nom}"
            contenu_html = f"""
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Rappel d'intervention</h2>
                    <p>Vous avez une prestation prévue demain :</p>
                    <ul>
                        <li><strong>Client :</strong> {client.prenom} {client.nom} ({client.telephone or 'Pas de tél'})</li>
                        <li><strong>Type :</strong> {prestation.type_prestation}</li>
                        <li><strong>Titre :</strong> {prestation.titre}</li>
                        <li><strong>Date :</strong> {prestation.date_debut.strftime('%d/%m/%Y à %H:%M')}</li>
                        <li><strong>Lieu :</strong> {prestation.adresse_prestation}, {prestation.code_postal_prestation} {prestation.ville_prestation}</li>
                        {f'<li><strong>Durée trajet :</strong> {prestation.duree_trajet_minutes // 60}h{prestation.duree_trajet_minutes % 60:02d} ({prestation.distance_km:.1f} km)</li>' if prestation.duree_trajet_minutes else ''}
                    </ul>
                    <p>Bon courage !</p>
                </body>
            </html>
            """
            contenu_sms = f"Rappel intervention demain {prestation.date_debut.strftime('%d/%m à %H:%M')} - {client.nom} - {prestation.titre} à {prestation.ville_prestation}"

        elif type_notif == 'facture_non_envoyee':
            sujet = f"Rappel : Facture à envoyer - {prestation.titre}"
            contenu_html = f"""
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Rappel Interne</h2>
                    <p>La prestation suivante a été réalisée il y a plus de 24h et aucune facture n'a été envoyée :</p>
                    <ul>
                        <li><strong>Client :</strong> {client.prenom} {client.nom}</li>
                        <li><strong>Prestation :</strong> {prestation.titre}</li>
                        <li><strong>Date :</strong> {prestation.date_debut.strftime('%d/%m/%Y')}</li>
                        <li><strong>Montant :</strong> {prestation.tarif_total} €</li>
                    </ul>
                    <p>Pensez à envoyer la facture !</p>
                </body>
            </html>
            """
            contenu_sms = f"Rappel : Facture à envoyer pour {client.nom} - {prestation.titre} ({prestation.tarif_total}€)"

        elif type_notif == 'facture_non_payee':
            sujet = f"Rappel de paiement - Facture {prestation.titre}"
            contenu_html = f"""
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Bonjour {client.prenom} {client.nom},</h2>
                    <p>Nous vous rappelons que la facture suivante est en attente de paiement :</p>
                    <ul>
                        <li><strong>Prestation :</strong> {prestation.titre}</li>
                        <li><strong>Date :</strong> {prestation.date_debut.strftime('%d/%m/%Y')}</li>
                        <li><strong>Montant :</strong> {prestation.tarif_total} €</li>
                        <li><strong>Délai de paiement :</strong> {client.delai_paiement_jours} jours</li>
                    </ul>
                    <p>Merci de procéder au règlement dans les meilleurs délais.</p>
                    <p>Cordialement,</p>
                </body>
            </html>
            """
            contenu_sms = f"Rappel de paiement : Facture {prestation.titre} - {prestation.tarif_total}€ en attente"

        else:
            return False, "Type de notification inconnu"

        # Déterminer le destinataire selon le type de notification
        if type_notif == 'rappel_prestation':
            # Rappel J-1 : envoyé à L'ENTREPRISE
            destinataire_nom = entreprise.nom if entreprise else "Entreprise"
            destinataire_email = entreprise.email if entreprise else None
            destinataire_tel = entreprise.telephone if entreprise else None
        else:
            # Autres notifications : envoyées au CLIENT
            destinataire_nom = f"{client.prenom} {client.nom}"
            destinataire_email = client.email
            destinataire_tel = client.telephone

        # Créer l'enregistrement de notification
        notification = Notification(
            type_notif=type_notif,
            prestation_id=prestation_id,
            destinataire_nom=destinataire_nom,
            destinataire_email=destinataire_email,
            destinataire_tel=destinataire_tel,
            canal=canal,
            statut='pending',
            date_programmee=datetime.utcnow(),
            contenu=contenu_sms if canal == 'sms' else contenu_html
        )

        # Envoyer selon le canal
        if canal == 'email':
            if not destinataire_email:
                notification.statut = 'failed'
                notification.erreur_message = "Aucun email pour le destinataire"
                db.session_presta.add(notification)
                db.session_presta.commit()
                return False, "Aucun email pour le destinataire"

            success, message = envoyer_email(destinataire_email, sujet, contenu_html)
        elif canal == 'sms':
            if not destinataire_tel:
                notification.statut = 'failed'
                notification.erreur_message = "Aucun téléphone pour le destinataire"
                db.session_presta.add(notification)
                db.session_presta.commit()
                return False, "Aucun téléphone pour le destinataire"

            success, message = envoyer_sms(destinataire_tel, contenu_sms)
        else:
            return False, "Canal inconnu"

        # Mettre à jour le statut de la notification
        if success:
            notification.statut = 'sent'
            notification.date_envoi = datetime.utcnow()
        else:
            notification.statut = 'failed'
            notification.erreur_message = message

        db.session_presta.add(notification)
        db.session_presta.commit()

        return success, message

    except Exception as e:
        return False, f"Erreur lors de la création de la notification: {str(e)}"


@app.route('/notifications/verifier')
def notifications_verifier():
    """
    Route pour vérifier et envoyer les notifications en attente
    À appeler périodiquement (via un cron ou manuellement)
    """
    try:
        entreprise = Entreprise.query.first()
        if not entreprise or not entreprise.notif_actives:
            return jsonify({'success': False, 'message': 'Notifications désactivées'})

        notifications_envoyees = []
        erreurs = []

        # 1. Vérifier les prestations de demain pour rappel EMAIL
        demain = datetime.now() + timedelta(days=1)
        debut_demain = demain.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_demain = demain.replace(hour=23, minute=59, second=59, microsecond=999999)

        prestations_demain = Prestation.query.filter(
            Prestation.date_debut >= debut_demain,
            Prestation.date_debut <= fin_demain,
            Prestation.statut.in_(['Planifiée', 'En cours'])
        ).all()

        for prestation in prestations_demain:
            # Vérifier si un rappel n'a pas déjà été envoyé
            notif_existante = Notification.query.filter_by(
                type_notif='rappel_prestation',
                prestation_id=prestation.id,
                statut='sent'
            ).first()

            if not notif_existante:
                success, message = creer_notification('rappel_prestation', prestation.id, canal='email')
                if success:
                    notifications_envoyees.append(f"Email rappel → Vous ({prestation.titre})")
                else:
                    erreurs.append(f"Erreur Email rappel {prestation.id}: {message}")

        # 2. Vérifier les factures non envoyées (prestations terminées depuis plus de 24h)
        il_y_a_24h = datetime.now() - timedelta(hours=24)
        prestations_terminees = Prestation.query.filter(
            Prestation.statut == 'Terminée',
            Prestation.date_fin < il_y_a_24h,
            Prestation.statut_paiement == 'En attente'
        ).all()

        for prestation in prestations_terminees:
            # Vérifier si une alerte n'a pas déjà été envoyée
            notif_existante = Notification.query.filter_by(
                type_notif='facture_non_envoyee',
                prestation_id=prestation.id,
                statut='sent'
            ).first()

            if not notif_existante and entreprise.email:
                # Envoyer à l'entreprise (rappel interne)
                success, message = creer_notification('facture_non_envoyee', prestation.id, canal='email')
                if success:
                    notifications_envoyees.append(f"Email rappel facture → Entreprise ({prestation.titre})")
                else:
                    erreurs.append(f"Erreur Email facture {prestation.id}: {message}")

        # 3. Vérifier les factures non payées (délai dépassé)
        for prestation in Prestation.query.filter_by(statut_paiement='En attente').all():
            if prestation.client and prestation.date_fin:
                delai = prestation.client.delai_paiement_jours or 30
                date_limite = prestation.date_fin + timedelta(days=delai)

                if datetime.now() > date_limite:
                    # Vérifier si un rappel n'a pas déjà été envoyé récemment (7 derniers jours)
                    il_y_a_7j = datetime.now() - timedelta(days=7)
                    notif_existante = Notification.query.filter(
                        Notification.type_notif == 'facture_non_payee',
                        Notification.prestation_id == prestation.id,
                        Notification.statut == 'sent',
                        Notification.date_envoi >= il_y_a_7j
                    ).first()

                    if not notif_existante:
                        success, message = creer_notification('facture_non_payee', prestation.id, canal='email')
                        if success:
                            notifications_envoyees.append(f"Email rappel paiement → {prestation.client.nom}")
                        else:
                            erreurs.append(f"Erreur Email paiement {prestation.id}: {message}")

        return jsonify({
            'success': True,
            'notifications_envoyees': notifications_envoyees,
            'nb_envoyees': len(notifications_envoyees),
            'erreurs': erreurs,
            'nb_erreurs': len(erreurs)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@app.route('/notifications/historique')
def notifications_historique():
    """Afficher l'historique des notifications"""
    notifications = Notification.query.order_by(Notification.date_programmee.desc()).limit(100).all()
    return render_template('notifications_historique.html', notifications=notifications)


# ============================================================================
# FONCTIONS RECHERCHE ENTREPRISES (OpenStreetMap)
# ============================================================================

def rechercher_entreprises_nominatim_direct(query):
    """
    Recherche directe avec Nominatim (sans séparation nom/ville)
    Ex: "leclerc carcassonne" cherché tel quel
    """
    import requests

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': f"{query}, France",
            'format': 'json',
            'limit': 20,
            'addressdetails': 1
        }
        headers = {'User-Agent': 'GestionEntreprise/1.0'}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        entreprises = []

        for result in data:
            # Vérifier que c'est bien un commerce/POI et pas juste une ville
            osm_type = result.get('type', '')
            if osm_type in ['city', 'town', 'village', 'municipality']:
                continue  # Ignorer les résultats qui sont juste des villes

            address = result.get('address', {})

            # Construire l'adresse
            rue = address.get('road', '')
            numero = address.get('house_number', '')
            if numero and rue:
                adresse_complete = f"{numero} {rue}"
            elif rue:
                adresse_complete = rue
            else:
                adresse_complete = ''

            # Extraire le nom (premier élément avant la virgule)
            nom_complet = result.get('display_name', '')
            nom = nom_complet.split(',')[0].strip()

            entreprise = {
                'nom': nom,
                'adresse': adresse_complete,
                'code_postal': address.get('postcode', ''),
                'ville': address.get('city') or address.get('town') or address.get('village', ''),
                'latitude': float(result.get('lat', 0)),
                'longitude': float(result.get('lon', 0))
            }

            entreprises.append(entreprise)

        return entreprises

    except Exception as e:
        print(f"Erreur Nominatim direct: {e}")
        return []

def rechercher_entreprises_nominatim(query, ville):
    """
    Rechercher des entreprises via Nominatim (plus adapté pour les POI)

    Args:
        query: Nom de l'entreprise
        ville: Nom de la ville

    Returns:
        Liste de dictionnaires avec les informations des entreprises
    """
    import requests

    try:
        # Rechercher avec Nominatim
        search_query = f"{query}, {ville}, France"
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': search_query,
            'format': 'json',
            'limit': 20,
            'addressdetails': 1
        }
        headers = {'User-Agent': 'GestionEntreprise/1.0'}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        entreprises = []

        for result in data:
            address = result.get('address', {})

            # Construire l'adresse
            rue = address.get('road', '')
            numero = address.get('house_number', '')
            if numero and rue:
                adresse_complete = f"{numero} {rue}"
            elif rue:
                adresse_complete = rue
            else:
                adresse_complete = ''

            entreprise = {
                'nom': result.get('display_name', '').split(',')[0],  # Premier élément = nom
                'adresse': adresse_complete,
                'code_postal': address.get('postcode', ''),
                'ville': address.get('city') or address.get('town') or address.get('village', ''),
                'latitude': float(result.get('lat', 0)),
                'longitude': float(result.get('lon', 0))
            }

            entreprises.append(entreprise)

        return entreprises

    except Exception as e:
        print(f"Erreur Nominatim: {e}")
        return []

def rechercher_entreprises_overpass(query, latitude=None, longitude=None, rayon_km=10):
    """
    Rechercher des entreprises via Overpass API (OpenStreetMap)

    Args:
        query: Nom de l'entreprise ou secteur d'activité
        latitude: Latitude du centre de recherche (optionnel)
        longitude: Longitude du centre de recherche (optionnel)
        rayon_km: Rayon de recherche en km (défaut: 10km)

    Returns:
        Liste de dictionnaires avec les informations des entreprises
    """
    import requests

    try:
        # Construire la requête Overpass
        # Échapper les caractères spéciaux pour la regex
        query_escaped = query.replace('[', '\\[').replace(']', '\\]').replace('(', '\\(').replace(')', '\\)')

        if latitude and longitude:
            # Recherche dans un rayon autour d'un point
            rayon_m = rayon_km * 1000
            # Recherche plus permissive : chercher tous les commerces puis filtrer
            # Utiliser .*leclerc.* pour matcher "E.Leclerc", "Leclerc", "leclerc drive", etc.
            overpass_query = f"""
            [out:json][timeout:25];
            (
              node["name"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              way["name"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              relation["name"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              node["brand"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              way["brand"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              relation["brand"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              node["operator"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
              way["operator"~".*{query_escaped}.*",i](around:{rayon_m},{latitude},{longitude});
            );
            out body center 100;
            """
        else:
            # Recherche globale (limité à 100 résultats)
            overpass_query = f"""
            [out:json][timeout:25];
            (
              node["name"~".*{query_escaped}.*",i];
              way["name"~".*{query_escaped}.*",i];
              node["brand"~".*{query_escaped}.*",i];
              way["brand"~".*{query_escaped}.*",i];
            );
            out body center 100;
            """

        print(f"[OVERPASS] Requête Overpass:\n{overpass_query}")

        # Appeler l'API Overpass
        url = "https://overpass-api.de/api/interpreter"
        response = requests.post(url, data={'data': overpass_query}, timeout=30)

        print(f"[OVERPASS] Statut réponse: {response.status_code}")

        if response.status_code != 200:
            print(f"[OVERPASS] Erreur HTTP: {response.text[:200]}")
            return []

        data = response.json()
        print(f"[OVERPASS] Éléments trouvés: {len(data.get('elements', []))}")
        entreprises = []

        # Extraire les informations
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            # Essayer 'name' puis 'brand' si name n'existe pas
            nom = tags.get('name') or tags.get('brand')

            if not nom:
                continue

            # Récupérer les coordonnées
            if element.get('type') == 'node':
                lat = element.get('lat')
                lon = element.get('lon')
            elif 'center' in element:
                lat = element['center'].get('lat')
                lon = element['center'].get('lon')
            else:
                lat = None
                lon = None

            # Construire l'adresse complète
            numero = tags.get('addr:housenumber', '')
            rue = tags.get('addr:street', '')
            if numero and rue:
                adresse_complete = f"{numero} {rue}"
            elif rue:
                adresse_complete = rue
            else:
                adresse_complete = ''

            entreprise = {
                'nom': nom,
                'adresse': adresse_complete,
                'code_postal': tags.get('addr:postcode', ''),
                'ville': tags.get('addr:city', ''),
                'telephone': tags.get('phone', ''),
                'email': tags.get('email', ''),
                'website': tags.get('website', ''),
                'secteur': tags.get('shop') or tags.get('amenity') or tags.get('office') or tags.get('craft', 'Autre'),
                'latitude': lat,
                'longitude': lon
            }

            # Calculer la distance depuis l'adresse de l'entreprise si possible
            if lat and lon and latitude and longitude:
                # Formule de Haversine pour calculer la distance
                from math import radians, sin, cos, sqrt, atan2
                R = 6371  # Rayon de la Terre en km

                lat1, lon1 = radians(latitude), radians(longitude)
                lat2, lon2 = radians(lat), radians(lon)

                dlat = lat2 - lat1
                dlon = lon2 - lon1

                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * atan2(sqrt(a), sqrt(1-a))
                distance = R * c

                entreprise['distance_km'] = round(distance, 1)

            entreprises.append(entreprise)

        # Trier par distance si disponible
        if latitude and longitude:
            entreprises.sort(key=lambda x: x.get('distance_km', 999999))

        return entreprises

    except Exception as e:
        print(f"Erreur Overpass API: {e}")
        return []

def rechercher_par_zone(ville, secteur=None, rayon_km=20):
    """
    Rechercher des entreprises dans une zone géographique

    Args:
        ville: Nom de la ville
        secteur: Secteur d'activité (optionnel)
        rayon_km: Rayon de recherche

    Returns:
        Liste des entreprises trouvées
    """
    import requests

    try:
        # D'abord géocoder la ville pour obtenir lat/lon
        geocode_url = f"https://nominatim.openstreetmap.org/search?q={ville}&format=json&limit=1"
        response = requests.get(geocode_url, headers={'User-Agent': 'GestionEntreprise/1.0'}, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        if not data:
            return []

        lat = float(data[0]['lat'])
        lon = float(data[0]['lon'])

        # Construire la requête selon le secteur
        rayon_m = rayon_km * 1000

        if secteur:
            # Recherche par secteur spécifique
            overpass_query = f"""
            [out:json][timeout:25];
            (
              node["shop"="{secteur}"](around:{rayon_m},{lat},{lon});
              way["shop"="{secteur}"](around:{rayon_m},{lat},{lon});
            );
            out body 100;
            """
        else:
            # Recherche toutes les entreprises (shop, office, amenity)
            overpass_query = f"""
            [out:json][timeout:25];
            (
              node["shop"](around:{rayon_m},{lat},{lon});
              node["office"](around:{rayon_m},{lat},{lon});
              node["amenity"="restaurant"](around:{rayon_m},{lat},{lon});
              node["amenity"="cafe"](around:{rayon_m},{lat},{lon});
              way["shop"](around:{rayon_m},{lat},{lon});
              way["office"](around:{rayon_m},{lat},{lon});
            );
            out body 100;
            """

        url = "https://overpass-api.de/api/interpreter"
        response = requests.post(url, data={'data': overpass_query}, timeout=30)

        if response.status_code != 200:
            return []

        data = response.json()
        entreprises = []

        for element in data.get('elements', []):
            tags = element.get('tags', {})
            nom = tags.get('name')

            if not nom:
                continue

            # Récupérer les coordonnées
            if element.get('type') == 'node':
                elem_lat = element.get('lat')
                elem_lon = element.get('lon')
            elif 'center' in element:
                elem_lat = element['center'].get('lat')
                elem_lon = element['center'].get('lon')
            else:
                elem_lat = None
                elem_lon = None

            entreprise = {
                'nom': nom,
                'adresse': tags.get('addr:street', ''),
                'numero': tags.get('addr:housenumber', ''),
                'code_postal': tags.get('addr:postcode', ''),
                'ville': tags.get('addr:city', ville),
                'telephone': tags.get('phone', ''),
                'email': tags.get('email', ''),
                'website': tags.get('website', ''),
                'secteur': tags.get('shop') or tags.get('office') or tags.get('amenity', 'Autre'),
                'latitude': elem_lat,
                'longitude': elem_lon
            }

            if entreprise['numero'] and entreprise['adresse']:
                entreprise['adresse_complete'] = f"{entreprise['numero']} {entreprise['adresse']}"
            elif entreprise['adresse']:
                entreprise['adresse_complete'] = entreprise['adresse']
            else:
                entreprise['adresse_complete'] = ''

            entreprises.append(entreprise)

        return entreprises

    except Exception as e:
        print(f"Erreur recherche par zone: {e}")
        return []

# ============================================================================
# NOUVEAU SYSTÈME GOOGLE CALENDAR - SIMPLE ET PROPRE
# ============================================================================

def get_google_calendar_service():
    """
    Connexion à Google Calendar
    Retourne le service ou None si erreur
    """
    print("🔄 Connexion à Google Calendar...")
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("❌ Fichier credentials.json introuvable")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    print("✅ Connecté à Google Calendar")
    return service


def creer_evenement_avec_rappels_personnalises(prestation, client, calendar_id='primary'):
    """
    Crée un événement Google Calendar avec rappels personnalisés

    Rappels :
    - La veille à 19h00
    - Le jour même à 7h00

    Args:
        prestation: objet Prestation de la base de données
        client: objet Client de la base de données
        calendar_id: ID du calendrier (default: 'primary')

    Returns:
        (success: bool, message: str, event_id: str ou None)
    """
    print("=" * 80)
    print("📅 CRÉATION ÉVÉNEMENT GOOGLE CALENDAR")
    print("=" * 80)

    try:
        # 1. Connexion à Google Calendar
        service = get_google_calendar_service()
        if not service:
            return False, "Impossible de se connecter à Google Calendar", None

        # 2. Récupérer les informations de la prestation
        print(f"📋 Prestation: {prestation.titre}")
        print(f"👤 Client: {client.prenom} {client.nom}")
        print(f"📧 Email: {client.email}")

        # 3. Construire le titre
        client_nom_complet = f"{client.prenom} {client.nom}" if client.prenom else client.nom
        titre = f"👤 {client_nom_complet} - {prestation.titre}"

        # 4. Construire la description
        description_parts = [
            f"Type: {prestation.type_prestation}",
            f"Client: {client_nom_complet}",
        ]
        if client.telephone:
            description_parts.append(f"Tél: {client.telephone}")
        if client.email:
            description_parts.append(f"Email: {client.email}")
        if prestation.demandeur:
            description_parts.append(f"Demandeur: {prestation.demandeur}")
        if prestation.adresse_prestation:
            description_parts.append(f"Adresse: {prestation.adresse_prestation}, {prestation.code_postal_prestation} {prestation.ville_prestation}")
        if prestation.description:
            description_parts.append(f"\n{prestation.description}")

        description = "\n".join(description_parts)

        # 5. Créer un événement par session
        events_created = []

        for idx, session in enumerate(prestation.sessions):
            print(f"\n📍 Session {idx + 1}/{len(prestation.sessions)}")

            # Titre avec numéro de session si plusieurs
            titre_session = titre
            if len(prestation.sessions) > 1:
                titre_session = f"{titre} (Session {idx + 1}/{len(prestation.sessions)})"

            # Dates
            start_time = session_presta.date_debut
            end_time = session_presta.date_fin if session_presta.date_fin else start_time + timedelta(hours=session_presta.duree_heures or 1)

            print(f"🕐 Début: {start_time}")
            print(f"🕐 Fin: {end_time}")

            # 6. CALCUL DES RAPPELS PERSONNALISÉS
            reminders_list = []

            if isinstance(start_time, datetime):
                event_start_dt = start_time
            else:
                # Si c'est une date seule, mettre 8h00
                event_start_dt = datetime.combine(start_time, datetime.min.time().replace(hour=8))

            print(f"\n🔔 Calcul des rappels pour: {event_start_dt}")

            # Rappel la veille à 19h00
            reminder_veille_datetime = event_start_dt.replace(hour=19, minute=0, second=0) - timedelta(days=1)
            minutes_veille = int((event_start_dt - reminder_veille_datetime).total_seconds() / 60)
            print(f"   📢 Rappel veille (19h): {minutes_veille} minutes avant")

            if 0 < minutes_veille < 40320:  # Google limite: 4 semaines
                reminders_list.append({'method': 'popup', 'minutes': minutes_veille})
                print(f"   ✅ Rappel veille AJOUTÉ")
            else:
                print(f"   ⚠️  Rappel veille IGNORÉ (hors limites)")

            # Rappel le jour même à 7h00
            reminder_jour_datetime = event_start_dt.replace(hour=7, minute=0, second=0)
            minutes_jour = int((event_start_dt - reminder_jour_datetime).total_seconds() / 60)
            print(f"   📢 Rappel jour (7h): {minutes_jour} minutes avant")

            if 0 < minutes_jour < 1440:  # Max 24h
                reminders_list.append({'method': 'popup', 'minutes': minutes_jour})
                print(f"   ✅ Rappel jour AJOUTÉ")
            else:
                print(f"   ⚠️  Rappel jour IGNORÉ (hors limites)")

            print(f"\n📋 Rappels finaux: {reminders_list}")

            # 7. Créer l'événement
            event_data = {
                'summary': titre_session,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'transparency': 'opaque',
                'reminders': {
                    'useDefault': False,
                    'overrides': reminders_list
                }
            }

            print(f"\n📤 Envoi à Google Calendar...")
            print(f"   Calendrier: {calendar_id}")
            print(f"   Rappels: {event_data['reminders']}")

            created_event = service.events().insert(
                calendarId=calendar_id,
                body=event_data
            ).execute()

            event_id = created_event['id']
            events_created.append(event_id)

            print(f"✅ Événement créé ! ID: {event_id}")
            print(f"🔗 URL: {created_event.get('htmlLink')}")

            # Vérifier les rappels enregistrés
            print(f"\n🔍 Vérification des rappels enregistrés...")
            event_check = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()

            rappels_enregistres = event_check.get('reminders', {})
            print(f"   useDefault: {rappels_enregistres.get('useDefault')}")
            print(f"   overrides: {rappels_enregistres.get('overrides')}")

        print("\n" + "=" * 80)
        print(f"✅ SUCCÈS ! {len(events_created)} événement(s) créé(s)")
        print("=" * 80)

        return True, f"{len(events_created)} événement(s) créé(s)", events_created[0] if events_created else None

    except Exception as e:
        print(f"\n❌ ERREUR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"Erreur: {str(e)}", None


# ============================================================================
# ANCIENNES FONCTIONS GOOGLE CALENDAR (À CONSERVER POUR COMPATIBILITÉ)
# ============================================================================
def get_calendar_service():
    """Retourne le service Google Calendar (avec authentification)"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        return None

    creds = None
    
    # Chercher credentials.json
    credentials_path = None
    for path in ['/etc/secrets/credentials.json', 'credentials.json']:
        if os.path.exists(path):
            credentials_path = path
            print(f"✅ Credentials trouvés : {path}")
            break
    
    if not credentials_path:
        print("❌ Fichier credentials.json introuvable")
        return None
    
    # Chercher token.json (priorité aux secrets persistants)
    token_path = None
    for path in ['/etc/secrets/token.json', 'token.json', '/tmp/token.json']:
        if os.path.exists(path):
            token_path = path
            print(f"✅ Token trouvé : {path}")
            break
    
    # Charger les credentials existants
    if token_path:
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            print(f"✅ Token chargé depuis {token_path}")
        except Exception as e:
            print(f"⚠️ Erreur chargement token : {e}")
            creds = None

    # Si pas de credentials valides
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            
    try:
        print("🔄 Rafraîchissement du token...")
        creds.refresh(Request())
        
        # Sauvegarder le token rafraîchi dans /tmp (Secret Files est read-only)
        save_path = '/tmp/token.json'
        with open(save_path, 'w') as token:
            token.write(creds.to_json())
        print(f"✅ Token rafraîchi et sauvegardé : {save_path}")
            except Exception as e:
                print(f"❌ Erreur refresh token : {e}")
                return None
        else:
            # Pas de token valide - l'utilisateur doit s'authentifier via /google-auth
            print("⚠️ Authentification requise via /google-auth")
            return None

    return build('calendar', 'v3', credentials=creds)

def get_filtered_calendars(service):
    """
    Récupère la liste des calendriers Google en excluant :
    - Les calendriers personnels (anniversaires, jours fériés)
    - Les calendriers non professionnels (task, sabine, etc.)
    - Les calendriers Google automatiques (contacts, etc.)
    """
    if not service:
        return []

    try:
        calendar_list = service.calendarList().list().execute()
        all_calendars = calendar_list.get('items', [])

        # Mots-clés à exclure (en minuscules)
        excluded_keywords = [
            'anniversaire', 'anniversaires',
            'jour férié', 'jours fériés', 'jours feries', 'fériés en france',
            'holiday', 'holidays', 'birthday', 'birthdays',
            'task', 'tasks', 'tâche', 'tâches',
            'sabine',
            'personnel', 'personal',
            'contact', 'contacts',
            'week numbers', 'numéros de semaine',
            'phases de la lune', 'moon phases'
        ]

        # Filtrer les calendriers
        filtered = []
        for cal in all_calendars:
            summary = cal.get('summary', '').lower()
            description = cal.get('description', '').lower()
            calendar_id = cal.get('id', '').lower()

            # Exclure les calendriers système de Google (contacts, etc.)
            if '#contacts@' in calendar_id or 'addressbook#' in calendar_id:
                continue

            # Exclure les calendriers de phases de lune, numéros de semaine, etc.
            if calendar_id.startswith('en.') or calendar_id.startswith('fr.'):
                # Ce sont souvent des calendriers de jours fériés régionaux
                if any(keyword in calendar_id for keyword in ['holiday', 'ferie']):
                    continue

            # Vérifier si le nom ou la description contient un mot-clé exclu
            is_excluded = any(keyword in summary or keyword in description for keyword in excluded_keywords)

            if not is_excluded:
                filtered.append(cal)

        return filtered

    except Exception as e:
        print(f"Erreur lors de la récupération des calendriers: {e}")
        return []


def creer_blocages_autres_calendriers(service, prestation, calendar_id_principal):
    """
    Créer des événements "🚫 Indisponible" sur tous les calendriers professionnels
    sauf celui où la prestation a été créée, pour chaque session
    """
    try:
        # Récupérer tous les calendriers professionnels
        tous_calendriers = get_filtered_calendars(service)

        # Filtrer pour ne garder que ceux qui ne sont PAS le calendrier principal de la prestation
        calendriers_a_bloquer = [cal for cal in tous_calendriers if cal['id'] != calendar_id_principal]

        if not calendriers_a_bloquer:
            return  # Aucun calendrier à bloquer

        # Supprimer les anciens blocages de cette prestation
        anciens_blocages = GcalBlocage.query.filter_by(prestation_id=prestation.id).all()
        for blocage in anciens_blocages:
            try:
                service.events().delete(
                    calendarId=blocage.calendar_id,
                    eventId=blocage.event_id
                ).execute()
            except:
                pass
            db.session_presta.delete(blocage)
        db.session_presta.commit()

        # Créer un événement de blocage pour CHAQUE session sur CHAQUE calendrier
        client = prestation.client
        client_nom = client.nom if client else "Client"

        if prestation.sessions and len(prestation.sessions) > 0:
            for session_presta in prestation.sessions:
                # Préparer l'événement de blocage pour cette session
                start_time = session_presta.date_debut
                end_time = session_presta.date_fin if session_presta.date_fin else start_time + timedelta(hours=session_presta.duree_heures or 1)

                if session_presta.journee_complete:
                    # Événement all-day
                    start_date = start_time.date() if hasattr(start_time, 'date') else start_time
                    end_date = end_time.date() if hasattr(end_time, 'date') else end_time
                    end_date_exclusive = end_date + timedelta(days=1)

                    event_blocage = {
                        'summary': '🚫 Indisponible',
                        'description': f'Occupé : {client_nom}',
                        'start': {'date': start_date.strftime('%Y-%m-%d')},
                        'end': {'date': end_date_exclusive.strftime('%Y-%m-%d')},
                        'transparency': 'opaque',
                        'visibility': 'private',
                    }
                else:
                    # Événement avec horaires
                    event_blocage = {
                        'summary': '🚫 Indisponible',
                        'description': f'Occupé : {client_nom}',
                        'start': {
                            'dateTime': start_time.isoformat(),
                            'timeZone': 'Europe/Paris',
                        },
                        'end': {
                            'dateTime': end_time.isoformat(),
                            'timeZone': 'Europe/Paris',
                        },
                        'transparency': 'opaque',
                        'visibility': 'private',
                    }

                # Créer le blocage sur chaque calendrier
                for cal in calendriers_a_bloquer:
                    try:
                        print("!!! CREATION BLOCAGE - LIGNE 4144 !!!")
                        print("event_blocage:", event_blocage)

                        created_blocage = service.events().insert(
                            calendarId=cal['id'],
                            body=event_blocage
                        ).execute()

                        print("!!! BLOCAGE CREE - ID:", created_blocage['id'])

                        # Enregistrer dans la BDD
                        nouveau_blocage = GcalBlocage(
                            prestation_id=prestation.id,
                            calendar_id=cal['id'],
                            event_id=created_blocage['id'],
                            calendar_name=cal.get('summary', 'Inconnu')
                        )
                        db.session_presta.add(nouveau_blocage)
                    except HttpError as e:
                        print(f"Erreur blocage calendrier {cal.get('summary', 'Inconnu')}: {e}")
                        pass

            db.session_presta.commit()

    except Exception as e:
        print(f"Erreur création blocages: {e}")


def creer_event_gcal_session(service, calendar_id, session, titre, description, start_time, end_time):
    """
    Créer un événement Google Calendar pour une session spécifique
    Retourne l'event_id ou None en cas d'erreur
    """
    try:
        print("========================================")
        print("CREER_EVENT_GCAL_SESSION - DEBUT")
        print("!!! session_presta.JOURNEE_COMPLETE =", session_presta.journee_complete, "!!!")
        print("!!! TYPE:", type(session_presta.journee_complete), "!!!")
        print("start_time:", start_time)
        print("start_time type:", type(start_time))

        # === RAPPELS GOOGLE CALENDAR AUTOMATIQUES ===
        reminders_list = []
        try:
            # datetime et timedelta sont déjà importés en haut du fichier
            event_start_dt = None

            # Convertir start_time en datetime si c'est un objet date
            if isinstance(start_time, datetime):
                event_start_dt = start_time
                print("start_time est datetime")
            elif hasattr(start_time, 'year'):  # C'est un objet date
                # Pour les journées complètes, prendre 8h00 le jour de début
                event_start_dt = datetime.combine(start_time, datetime.min.time().replace(hour=8))
                print("start_time converti en datetime")

            print("event_start_dt:", event_start_dt)

            if event_start_dt:
                # Rappel la veille à 19h00
                reminder_veille = event_start_dt.replace(hour=19, minute=0, second=0) - timedelta(days=1)
                minutes_veille = int((event_start_dt - reminder_veille).total_seconds() / 60)
                print("Calcul rappel veille - minutes:", minutes_veille)
                if minutes_veille > 0 and minutes_veille < 40320:
                    reminders_list.append({'method': 'popup', 'minutes': minutes_veille})
                    print("Rappel veille ajoute")

                # Rappel le jour même à 7h00
                reminder_jour = event_start_dt.replace(hour=7, minute=0, second=0)
                minutes_jour = int((event_start_dt - reminder_jour).total_seconds() / 60)
                print("Calcul rappel jour - minutes:", minutes_jour)
                if minutes_jour > 0 and minutes_jour < 1440:
                    reminders_list.append({'method': 'popup', 'minutes': minutes_jour})
                    print("Rappel jour ajoute")
        except Exception as e:
            print("ERREUR calcul rappels:", str(e))

        print("reminders_list FINAL:", reminders_list)
        print("========================================")
        # === FIN RAPPELS ===

        # MODIFICATION : Gérer les prestations "Journée complète"
        # Si multi-jours : créer 1 événement par jour (08:00-20:00)
        # Si 1 jour : créer 1 événement (08:00-20:00)
        if session_presta.journee_complete:
            print("🌞 JOURNÉE COMPLÈTE DÉTECTÉE")

            # Extraire les dates
            start_date = start_time.date() if hasattr(start_time, 'date') else start_time
            end_date = end_time.date() if hasattr(end_time, 'date') else end_time

            # Calculer le nombre de jours
            nb_jours = (end_date - start_date).days + 1
            print(f"📅 Nombre de jours : {nb_jours} (du {start_date} au {end_date})")

            if nb_jours > 1:
                # MULTI-JOURS : Créer un événement pour chaque jour
                print(f"🔄 MULTI-JOURS : Création de {nb_jours} événements séparés")

                event_ids = []
                current_date = start_date

                while current_date <= end_date:
                    jour_num = (current_date - start_date).days + 1

                    # Titre avec numéro de jour
                    titre_jour = f"{titre} (Jour {jour_num}/{nb_jours})"

                    # Horaires : 08:00 - 20:00 pour ce jour
                    start_datetime = datetime.combine(current_date, datetime.min.time().replace(hour=8, minute=0))
                    end_datetime = datetime.combine(current_date, datetime.min.time().replace(hour=20, minute=0))

                    # Calculer les rappels pour CE jour spécifiquement
                    rappels_jour = []

                    # Rappel veille à 19h00
                    veille_19h = datetime.combine(current_date, datetime.min.time().replace(hour=19, minute=0)) - timedelta(days=1)
                    minutes_veille = int((start_datetime - veille_19h).total_seconds() / 60)
                    if 0 < minutes_veille < 10080:  # Max 7 jours
                        rappels_jour.append({'method': 'popup', 'minutes': minutes_veille})

                    # Rappel jour à 07h00
                    jour_7h = datetime.combine(current_date, datetime.min.time().replace(hour=7, minute=0))
                    minutes_jour_rappel = int((start_datetime - jour_7h).total_seconds() / 60)
                    if 0 < minutes_jour_rappel < 1440:  # Max 24h
                        rappels_jour.append({'method': 'popup', 'minutes': minutes_jour_rappel})

                    print(f"   📌 Jour {jour_num}/{nb_jours} : {current_date} avec {len(rappels_jour)} rappels")

                    # Créer l'événement pour ce jour
                    event_data = {
                        'summary': titre_jour,
                        'description': description,
                        'start': {
                            'dateTime': start_datetime.isoformat(),
                            'timeZone': 'Europe/Paris',
                        },
                        'end': {
                            'dateTime': end_datetime.isoformat(),
                            'timeZone': 'Europe/Paris',
                        },
                        'transparency': 'opaque',
                        'reminders': {
                            'useDefault': False,
                            'overrides': rappels_jour
                        }
                    }

                    created_event = service.events().insert(
                        calendarId=calendar_id,
                        body=event_data
                    ).execute()

                    event_ids.append(created_event['id'])
                    print(f"   ✅ Événement créé - ID: {created_event['id']}")

                    # Passer au jour suivant
                    current_date += timedelta(days=1)

                print(f"✅ {len(event_ids)} événements créés pour prestation multi-jours")
                # Retourner le premier ID (pour compatibilité)
                return event_ids[0] if event_ids else None

            else:
                # UN SEUL JOUR : Créer 1 événement 08:00-20:00
                print("📅 UN SEUL JOUR : Création d'1 événement 08:00-20:00")

                start_datetime = datetime.combine(start_date, datetime.min.time().replace(hour=8, minute=0))
                end_datetime = datetime.combine(start_date, datetime.min.time().replace(hour=20, minute=0))

                event_data = {
                    'summary': titre,
                    'description': description,
                    'start': {
                        'dateTime': start_datetime.isoformat(),
                        'timeZone': 'Europe/Paris',
                    },
                    'end': {
                        'dateTime': end_datetime.isoformat(),
                        'timeZone': 'Europe/Paris',
                    },
                    'transparency': 'opaque',
                    'reminders': {
                        'useDefault': False,
                        'overrides': reminders_list
                    }
                }
        else:
            # PAS "Journée complète" : événement normal avec horaires spécifiques
            print("⏰ Événement avec horaires spécifiques (Matin/Après-midi/Personnalisé)")

            event_data = {
                'summary': titre,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'transparency': 'opaque',
                'reminders': {
                    'useDefault': False,
                    'overrides': reminders_list
                }
            }

        # Créer l'événement (pour les cas 1 jour ou horaires spécifiques)
        print(">>> ENVOI À GOOGLE CALENDAR <<<")
        print(">>> Rappels configurés:", len(event_data.get('reminders', {}).get('overrides', [])))

        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event_data
        ).execute()

        print(">>> ÉVÉNEMENT CRÉÉ - ID:", created_event['id'])
        print(">>> Rappels enregistrés:", created_event.get('reminders'))

        return created_event['id']

    except Exception as e:
        print(f"Erreur création événement session: {e}")
        return None


def sync_prestation_to_gcal(prestation_id):
    """
    Synchroniser une prestation vers Google Calendar
    Retourne (success: bool, message: str, event_id: str)
    """
    print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
    print("SYNC_PRESTATION_TO_GCAL APPELEE !!!!")
    print("prestation_id:", prestation_id)
    print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")

    try:
        if not GOOGLE_CALENDAR_AVAILABLE:
            return False, "Modules Google Calendar non installés", None

        prestation = Prestation.query.get(prestation_id)
        if not prestation:
            return False, "Prestation introuvable", None

        service = get_calendar_service()
        if not service:
            return False, "Service Google Calendar non disponible. Configurez credentials.json", None

        # Charger la configuration des calendriers
        config = CalendrierConfig.query.first()

        # NOUVELLE LOGIQUE : Chaque prestation va sur SON PROPRE calendrier
        # Si prestation.calendrier_id est défini, on l'utilise
        # Sinon, on utilise le calendrier principal configuré
        calendar_id = 'primary'  # Par défaut
        calendrier_principal_id = 'primary'  # Pour les événements "Indisponible"

        if config and config.config_json:
            try:
                config_data = json.loads(config.config_json)
                calendrier_principal_id = config_data.get('calendrier_principal', {}).get('id', 'primary')
            except:
                pass

        # Récupérer le client de la prestation
        client = prestation.client

        # LOGIQUE DE SÉLECTION DU CALENDRIER (par ordre de priorité) :
        # 1. Si prestation.calendrier_id est défini → utiliser ce calendrier
        # 2. Sinon, si client.calendrier_google est défini → utiliser le calendrier du client
        # 3. Sinon → utiliser le calendrier principal (Michel Boyer)
        print("🟢🟢🟢 SÉLECTION DU CALENDRIER 🟢🟢🟢")
        print("prestation.calendrier_id:", prestation.calendrier_id)
        print("client.calendrier_google:", client.calendrier_google if client else None)
        print("calendrier_principal_id:", calendrier_principal_id)

        if prestation.calendrier_id:
            calendar_id = prestation.calendrier_id
            print("✅ Calendrier choisi : prestation.calendrier_id")
        elif client and client.calendrier_google:
            calendar_id = client.calendrier_google
            print("✅ Calendrier choisi : client.calendrier_google")
        else:
            calendar_id = calendrier_principal_id
            print("✅ Calendrier choisi : calendrier_principal_id (par défaut)")

        print("📌 calendar_id FINAL:", calendar_id)
        print("🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢")

        # Préparer l'événement
        # Construire le titre avec le nom client propre (sans "None")
        client_nom_complet = ''
        if client.prenom:
            client_nom_complet = client.prenom + ' ' + client.nom
        else:
            client_nom_complet = client.nom

        titre = f"👤 {client_nom_complet} - {prestation.titre}"

        description_parts = [
            f"Type: {prestation.type_prestation}",
            f"Client: {client_nom_complet}",
        ]
        if client.telephone:
            description_parts.append(f"Tél: {client.telephone}")
        if client.email:
            description_parts.append(f"Email: {client.email}")
        if prestation.demandeur:
            description_parts.append(f"Demandeur: {prestation.demandeur}")
        if prestation.adresse_prestation:
            description_parts.append(f"Adresse: {prestation.adresse_prestation}, {prestation.code_postal_prestation} {prestation.ville_prestation}")
        if prestation.description:
            description_parts.append(f"\n{prestation.description}")

        description = "\n".join(description_parts)

        # NOUVELLE LOGIQUE : Créer un événement Google Calendar PAR SESSION
        # Au lieu de créer un seul événement basé sur date_debut/date_fin de la prestation
        events_created = []

        if prestation.sessions and len(prestation.sessions) > 0:
            # Cas avec sessions multiples : créer un événement par session
            for idx, session in enumerate(prestation.sessions):
                # Titre avec numéro de session si plusieurs sessions
                titre_session = titre
                if len(prestation.sessions) > 1:
                    titre_session = f"{titre} (Session {idx + 1}/{len(prestation.sessions)})"

                # Utiliser les dates de la session
                start_time = session_presta.date_debut
                end_time = session_presta.date_fin if session_presta.date_fin else start_time + timedelta(hours=session_presta.duree_heures or 1)

                # Créer l'événement pour cette session
                event_id = creer_event_gcal_session(
                    service, calendar_id, session, titre_session, description,
                    start_time, end_time
                )
                if event_id:
                    events_created.append(event_id)
                    # Enregistrer l'ID de l'événement sur la session
                    session_presta.gcal_event_id = event_id
                    session_presta.gcal_synced = True

            # Mettre à jour la prestation principale
            prestation.gcal_synced = True
            prestation.gcal_last_sync = datetime.utcnow()
            if events_created:
                # Stocker l'ID du premier événement (pour compatibilité)
                prestation.gcal_event_id = events_created[0]
            db.session_presta.commit()

            # Créer les événements "Indisponible" sur TOUS les autres calendriers professionnels
            # pour bloquer ces créneaux (sauf le calendrier où la prestation est créée)
            creer_blocages_autres_calendriers(service, prestation, calendar_id)

            return True, f"{len(events_created)} événement(s) créé(s)", events_created[0] if events_created else None

        # FALLBACK : Ancien code pour les prestations sans sessions
        start_time = prestation.date_debut
        if prestation.date_fin:
            end_time = prestation.date_fin
        elif prestation.duree_heures:
            end_time = start_time + timedelta(hours=prestation.duree_heures)
        else:
            end_time = start_time + timedelta(hours=1)  # Par défaut 1h

        # === RAPPELS GOOGLE CALENDAR AUTOMATIQUES ===
        reminders_list = []
        try:
            # datetime et timedelta sont déjà importés en haut du fichier
            event_start_dt = None

            # Convertir start_time en datetime si c'est un objet date
            if isinstance(start_time, datetime):
                event_start_dt = start_time
            elif hasattr(start_time, 'year'):  # C'est un objet date
                # Pour les journées complètes, prendre 8h00 le jour de début
                event_start_dt = datetime.combine(start_time, datetime.min.time().replace(hour=8))

            if event_start_dt:
                # Rappel la veille à 19h00
                reminder_veille = event_start_dt.replace(hour=19, minute=0, second=0) - timedelta(days=1)
                minutes_veille = int((event_start_dt - reminder_veille).total_seconds() / 60)
                if minutes_veille > 0 and minutes_veille < 40320:
                    reminders_list.append({'method': 'popup', 'minutes': minutes_veille})

                # Rappel le jour même à 7h00
                reminder_jour = event_start_dt.replace(hour=7, minute=0, second=0)
                minutes_jour = int((event_start_dt - reminder_jour).total_seconds() / 60)
                if minutes_jour > 0 and minutes_jour < 1440:
                    reminders_list.append({'method': 'popup', 'minutes': minutes_jour})
        except Exception as e:
            pass
        # === FIN RAPPELS ===

        # MODIFICATION : Au lieu de créer un événement "all day", on crée 08h00-20h00
        # pour que les rappels personnalisés fonctionnent correctement
        if prestation.journee_entiere:
            print("\n" + "="*80)
            print("ATTENTION ATTENTION ATTENTION")
            print("CREATION EVENEMENT 08H00-20H00 AU LIEU DE JOURNEE ENTIERE")
            print("="*80 + "\n")

            # Extraire la date de début
            start_date = start_time.date() if hasattr(start_time, 'date') else start_time
            end_date = end_time.date() if hasattr(end_time, 'date') else end_time

            # Créer un événement avec heures précises : 08h00-20h00
            start_datetime = datetime.combine(start_date, datetime.min.time().replace(hour=8, minute=0))
            end_datetime = datetime.combine(end_date, datetime.min.time().replace(hour=20, minute=0))

            print(f"Start: {start_datetime}")
            print(f"End: {end_datetime}")
            print("="*80)

            event_data = {
                'summary': titre,
                'description': description,
                'start': {
                    'dateTime': start_datetime.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'transparency': 'opaque',
            'reminders': {
                'useDefault': False,
                'overrides': reminders_list if reminders_list else []
            }
            }
        else:
            event_data = {
                'summary': titre,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'transparency': 'opaque',
            'reminders': {
                'useDefault': False,
                'overrides': reminders_list if reminders_list else []
            }
            }

        # Si l'événement existe déjà, le mettre à jour
        if prestation.gcal_event_id:
            try:
                updated_event = service.events().update(
                    calendarId=calendar_id,
                    eventId=prestation.gcal_event_id,
                    body=event_data
                ).execute()

                prestation.gcal_synced = True
                prestation.gcal_last_sync = datetime.utcnow()
                db.session_presta.commit()

                return True, "Événement Google Calendar mis à jour", updated_event['id']
            except HttpError as e:
                # Si l'événement n'existe plus, en créer un nouveau
                if e.resp.status == 404:
                    prestation.gcal_event_id = None
                else:
                    return False, f"Erreur lors de la mise à jour: {str(e)}", None

        # Créer un nouvel événement
        print("!!! CREATION PRESTATION FALLBACK - LIGNE 4515 !!!")
        print("event_data reminders:", event_data.get('reminders'))

        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event_data
        ).execute()

        print("!!! PRESTATION FALLBACK CREEE - ID:", created_event['id'])
        print("!!! Rappels enregistres:", created_event.get('reminders'))

        # Mettre à jour la prestation
        prestation.gcal_event_id = created_event['id']
        prestation.gcal_synced = True
        prestation.gcal_last_sync = datetime.utcnow()
        db.session_presta.commit()

        # Créer l'événement "Indisponible" sur le calendrier principal (michel boyer)
        # et sur les autres calendriers configurés
        if config and config.config_json:
            try:
                config_data = json.loads(config.config_json)
                calendriers_a_bloquer = config_data.get('calendriers_a_bloquer', [])

                # Ajouter le calendrier principal à la liste des calendriers à bloquer
                # (sauf si la prestation est déjà sur ce calendrier = pas d'email client)
                if client.email and calendrier_principal_id:
                    # Ajouter le calendrier principal à bloquer
                    cal_principal = {
                        'id': calendrier_principal_id,
                        'nom': 'Calendrier principal'
                    }
                    # Créer une nouvelle liste avec le calendrier principal en premier
                    tous_calendriers_a_bloquer = [cal_principal] + calendriers_a_bloquer
                else:
                    # Si pas d'email client, la prestation est déjà sur le principal,
                    # donc bloquer seulement les autres
                    tous_calendriers_a_bloquer = calendriers_a_bloquer

                if tous_calendriers_a_bloquer:
                    # Préparer l'événement de blocage
                    if prestation.journee_entiere:
                        event_blocage = {
                            'summary': '🚫 Indisponible',
                            'description': f'Occupé : {client.nom}',
                            'start': {
                                'date': start_time.strftime('%Y-%m-%d'),
                            },
                            'end': {
                                'date': (end_time + timedelta(days=1)).strftime('%Y-%m-%d'),
                            },
                            'transparency': 'opaque',
                            'visibility': 'private',
                        }
                    else:
                        event_blocage = {
                            'summary': '🚫 Indisponible',
                            'description': f'Occupé : {client.nom}',
                            'start': {
                                'dateTime': start_time.isoformat(),
                                'timeZone': 'Europe/Paris',
                            },
                            'end': {
                                'dateTime': end_time.isoformat(),
                                'timeZone': 'Europe/Paris',
                            },
                            'transparency': 'opaque',
                            'visibility': 'private',
                        }

                    # Supprimer les anciens événements de blocage si mis à jour
                    if prestation.gcal_event_id:
                        anciens_blocages = GcalBlocage.query.filter_by(prestation_id=prestation_id).all()
                        for blocage in anciens_blocages:
                            try:
                                service.events().delete(
                                    calendarId=blocage.calendar_id,
                                    eventId=blocage.event_id
                                ).execute()
                            except:
                                pass
                            db.session_presta.delete(blocage)
                        db.session_presta.commit()

                    # Créer l'événement de blocage sur chaque calendrier
                    for cal in tous_calendriers_a_bloquer:
                        try:
                            print("!!! CREATION BLOCAGE 2 - LIGNE 4602 !!!")
                            print("event_blocage:", event_blocage)

                            created_blocage = service.events().insert(
                                calendarId=cal['id'],
                                body=event_blocage
                            ).execute()

                            print("!!! BLOCAGE 2 CREE - ID:", created_blocage['id'])

                            # Enregistrer le blocage dans la base de données
                            nouveau_blocage = GcalBlocage(
                                prestation_id=prestation_id,
                                calendar_id=cal['id'],
                                event_id=created_blocage['id'],
                                calendar_name=cal['nom']
                            )
                            db.session_presta.add(nouveau_blocage)
                        except HttpError as e:
                            # Ignorer les erreurs de calendriers individuels
                            print(f"Erreur blocage calendrier {cal['nom']}: {e}")
                            pass
                    db.session_presta.commit()
            except:
                pass

        return True, "Événement créé sur Google Calendar", created_event['id']

    except HttpError as e:
        return False, f"Erreur Google Calendar API: {str(e)}", None
    except Exception as e:
        return False, f"Erreur: {str(e)}", None


def delete_gcal_event(prestation_id):
    """
    Supprimer l'événement Google Calendar d'une prestation
    Retourne (success: bool, message: str)
    """
    try:
        if not GOOGLE_CALENDAR_AVAILABLE:
            return False, "Modules Google Calendar non installés"

        prestation = Prestation.query.get(prestation_id)
        if not prestation or not prestation.gcal_event_id:
            return True, "Aucun événement à supprimer"

        service = get_calendar_service()
        if not service:
            return False, "Service Google Calendar non disponible"

        # Utiliser la MÊME logique de sélection du calendrier que pour la création :
        # 1. prestation.calendrier_id (si défini)
        # 2. client.calendrier_google (si défini)
        # 3. calendrier principal (par défaut)
        client = Client.query.get(prestation.client_id) if prestation.client_id else None

        # Charger le calendrier principal depuis la config
        config = CalendrierConfig.query.first()
        calendrier_principal_id = 'primary'
        if config and config.config_json:
            try:
                config_data = json.loads(config.config_json)
                calendrier_principal_id = config_data.get('calendrier_principal', {}).get('id', 'primary')
            except:
                pass

        # Sélection du calendrier (même logique que sync_prestation_to_gcal)
        if prestation.calendrier_id:
            calendar_id = prestation.calendrier_id
        elif client and client.calendrier_google:
            calendar_id = client.calendrier_google
        else:
            calendar_id = calendrier_principal_id

        print(f"🗑️ Suppression événement - calendar_id: {calendar_id}")

        # Supprimer l'événement
        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=prestation.gcal_event_id
            ).execute()

            prestation.gcal_event_id = None
            prestation.gcal_synced = False
            db.session_presta.commit()

            # Supprimer aussi les blocages sur les autres calendriers en utilisant la nouvelle table
            nb_blocages_supprimes = 0
            try:
                blocages = GcalBlocage.query.filter_by(prestation_id=prestation_id).all()

                for blocage in blocages:
                    try:
                        service.events().delete(
                            calendarId=blocage.calendar_id,
                            eventId=blocage.event_id
                        ).execute()
                        nb_blocages_supprimes += 1
                    except HttpError as e:
                        if e.resp.status != 404:  # Ignorer si l'événement n'existe déjà plus
                            print(f"Erreur suppression blocage {blocage.calendar_name}: {e}")
                    except Exception as e:
                        print(f"Erreur suppression blocage {blocage.calendar_name}: {e}")

                    # Supprimer l'enregistrement du blocage de la base de données
                    db.session_presta.delete(blocage)

                db.session_presta.commit()
            except Exception as e:
                # Si la table gcal_blocages n'existe pas encore (migration non faite), ignorer
                print(f"Note: Impossible de supprimer les blocages: {e}")
                pass

            message = "Événement supprimé de Google Calendar"
            if nb_blocages_supprimes > 0:
                message += f" et {nb_blocages_supprimes} blocage(s) supprimé(s)"

            return True, message
        except HttpError as e:
            if e.resp.status == 404:
                # L'événement n'existe déjà plus
                prestation.gcal_event_id = None
                prestation.gcal_synced = False
                db.session_presta.commit()
                return True, "Événement déjà supprimé"
            else:
                return False, f"Erreur lors de la suppression: {str(e)}"

    except Exception as e:
        return False, f"Erreur: {str(e)}"

# ============================================================================
# ROUTES OAUTH GOOGLE CALENDAR (pour le web)
# ============================================================================

@app.route('/google-auth')
def google_auth():
    """Démarrer l'authentification Google OAuth"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        flash('❌ Modules Google Calendar non installés', 'error')
        return redirect(url_for('index'))
    
    credentials_path = None
    for path in ['/etc/secrets/credentials.json', 'credentials.json']:
        if os.path.exists(path):
            credentials_path = path
            break
    
    if not credentials_path:
        flash('❌ Fichier credentials.json introuvable', 'error')
        return redirect(url_for('index'))
    
    try:
        flow = Flow.from_client_secrets_file(
            credentials_path, 
            scopes=SCOPES,
            redirect_uri='https://gestion-ets.onrender.com/oauth2callback'
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        session['oauth_state'] = state
        return redirect(authorization_url)
    
    except Exception as e:
        flash(f'❌ Erreur OAuth : {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/oauth2callback')
def oauth2callback():
    """Callback après authentification Google"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        flash('❌ Modules Google Calendar non installés', 'error')
        return redirect(url_for('index'))
    
    credentials_path = None
    for path in ['/etc/secrets/credentials.json', 'credentials.json']:
        if os.path.exists(path):
            credentials_path = path
            break
    
    if not credentials_path:
        flash('❌ Fichier credentials.json introuvable', 'error')
        return redirect(url_for('index'))
    
    try:
        flow = Flow.from_client_secrets_file(
            credentials_path,
            scopes=SCOPES,
            redirect_uri='https://gestion-ets.onrender.com/oauth2callback'
        )
        
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        
        token_path = '/tmp/token.json' if os.environ.get('RENDER') else 'token.json'
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        
        flash('✅ Authentification Google Calendar réussie !', 'success')
        return redirect(url_for('gcal_config'))
    
    except Exception as e:
        flash(f'❌ Erreur callback OAuth : {str(e)}', 'error')
        return redirect(url_for('index'))
# ============================================================================
# ROUTES GOOGLE CALENDAR
# ============================================================================

@app.route('/prestation/<int:prestation_id>/sync-gcal', methods=['POST'])
def prestation_sync_gcal(prestation_id):
    """Synchroniser manuellement une prestation vers Google Calendar"""
    success, message, event_id = sync_prestation_to_gcal(prestation_id)

    if success:
        flash(f'✓ {message}', 'success')
    else:
        flash(f'❌ {message}', 'error')

    return redirect(url_for('prestation_detail', prestation_id=prestation_id))


@app.route('/prestation/<int:prestation_id>/unsync-gcal', methods=['POST'])
def prestation_unsync_gcal(prestation_id):
    """Supprimer l'événement Google Calendar d'une prestation"""
    success, message = delete_gcal_event(prestation_id)

    if success:
        flash(f'✓ {message}', 'success')
    else:
        flash(f'❌ {message}', 'error')

    return redirect(url_for('prestation_detail', prestation_id=prestation_id))


@app.route('/gcal/config', methods=['GET', 'POST'])
def gcal_config():
    """Configuration des calendriers Google"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        flash('❌ Modules Google Calendar non installés', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Récupérer les calendriers à bloquer depuis le JSON
        calendriers_a_bloquer = []
        calendriers_bloquer_ids = []
        try:
            calendriers_bloquer_json = request.form.get('calendriers_bloquer_json', '[]')
            calendriers_a_bloquer = json.loads(calendriers_bloquer_json)
            calendriers_bloquer_ids = [cal['id'] for cal in calendriers_a_bloquer]
        except:
            pass

        # Sauvegarder la configuration
        config_data = {
            'calendrier_principal': {
                'id': request.form.get('calendar_id', 'primary'),
                'nom': request.form.get('calendar_name', 'Principal')
            },
            'auto_sync': request.form.get('auto_sync') == 'on',
            'calendriers_a_bloquer': calendriers_a_bloquer,
            'calendriers_a_bloquer_ids': calendriers_bloquer_ids
        }

        config = CalendrierConfig.query.first()
        if config:
            config.config_json = json.dumps(config_data)
        else:
            config = CalendrierConfig(config_json=json.dumps(config_data))
            db.session_presta.add(config)

        db.session_presta.commit()

        nb_calendriers_bloquer = len(calendriers_a_bloquer)
        if nb_calendriers_bloquer > 0:
            flash(f'✓ Configuration Google Calendar enregistrée ({nb_calendriers_bloquer} calendrier(s) à bloquer)', 'success')
        else:
            flash('✓ Configuration Google Calendar enregistrée', 'success')

        return redirect(url_for('gcal_config'))

    # Récupérer les calendriers disponibles
    calendars = []
    try:
        service = get_calendar_service()
        if service:
            calendars = get_filtered_calendars(service)
    except Exception as e:
        flash(f'⚠️ Erreur lors de la récupération des calendriers: {str(e)}', 'warning')

    # Charger la configuration actuelle
    config = CalendrierConfig.query.first()
    current_config = {}
    if config and config.config_json:
        try:
            current_config = json.loads(config.config_json)
        except:
            pass

    return render_template('gcal_config.html', calendars=calendars, current_config=current_config)


@app.route('/gcal/sync-all', methods=['POST'])
def gcal_sync_all():
    """Synchroniser toutes les prestations planifiées vers Google Calendar"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        flash('❌ Modules Google Calendar non installés', 'error')
        return redirect(url_for('index'))

    prestations = Prestation.query.filter(
        Prestation.statut.in_(['Planifiée', 'En cours'])
    ).all()

    success_count = 0
    error_count = 0

    for prestation in prestations:
        success, message, event_id = sync_prestation_to_gcal(prestation.id)
        if success:
            success_count += 1
        else:
            error_count += 1

    if error_count == 0:
        flash(f'✓ {success_count} prestation(s) synchronisée(s) avec Google Calendar', 'success')
    else:
        flash(f'⚠️ {success_count} succès, {error_count} erreur(s)', 'warning')

    return redirect(url_for('prestations'))


@app.route('/quitter', methods=['POST'])
def quitter():
    """Arrêter proprement l'application Flask avec sauvegarde automatique"""
    import os
    import signal

    def sauvegarder_et_fermer():
        """Créer une sauvegarde automatique puis fermer le serveur"""
        import time
        try:
            # Créer une sauvegarde automatique
            timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')
            nom_fichier = f"gestion_entreprise_AUTO_{timestamp}.db"

            # Chemins de sauvegarde
            chemin_local = os.path.join(app.config['BACKUP_FOLDER'], nom_fichier)
            chemin_gdrive = os.path.join(app.config['GDRIVE_BACKUP_PATH'], nom_fichier)

            # Copier la base de données locale
            db_source = os.path.join(os.getcwd(), 'instance', 'gestion_entreprise.db')
            if os.path.exists(db_source):
                shutil.copy2(db_source, chemin_local)
                taille = os.path.getsize(chemin_local)

                # Tenter la copie vers Google Drive
                statut_gdrive = 'N/A'
                chemin_gdrive_final = None

                try:
                    os.makedirs(app.config['GDRIVE_BACKUP_PATH'], exist_ok=True)
                    shutil.copy2(chemin_local, chemin_gdrive)
                    statut_gdrive = 'Success'
                    chemin_gdrive_final = chemin_gdrive
                except:
                    statut_gdrive = 'Failed'

                # Enregistrer la sauvegarde dans la base
                with app.app_context():
                    sauvegarde = Sauvegarde(
                        nom_fichier=nom_fichier,
                        taille_octets=taille,
                        chemin_local=chemin_local,
                        chemin_gdrive=chemin_gdrive_final,
                        statut_gdrive=statut_gdrive,
                        notes="Sauvegarde automatique à la fermeture"
                    )
                    db.session_presta.add(sauvegarde)
                    db.session_presta.commit()

                print(f"\n✅ Sauvegarde automatique créée : {nom_fichier}")
        except Exception as e:
            print(f"\n⚠️ Erreur lors de la sauvegarde automatique : {e}")

        # Attendre un peu puis fermer le serveur
        time.sleep(1.5)
        os.kill(os.getpid(), signal.SIGINT)

    # Lancer la sauvegarde et fermeture dans un thread séparé
    import threading
    thread = threading.Thread(target=sauvegarder_et_fermer)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Sauvegarde en cours puis fermeture de l\'application...'
    })


# ============================================================================
# INITIALISATION
# ============================================================================

def init_db():
    """Initialiser la base de données"""
    with app.app_context():
        db.create_all()

        # Créer l'utilisateur admin par défaut s'il n'existe pas
    admin = Utilisateur.query.filter_by(username='admin').first()
    if not admin:
        admin = Utilisateur(
            username='admin',
            nom='Administrateur',
            email='m.boyer3215@gmail.com',
            role='admin'
        )
        admin.set_password('MiB2025!')  # Change ce mot de passe !
        db.session_presta.add(admin)
        db.session_presta.commit()
        print("✅ Utilisateur admin créé (mot de passe: MiB2025!)")
        
        print("✅ Base de données initialisée !")

# Initialisation au démarrage
with app.app_context():
    db.create_all()
    print("✅ Tables créées")
    
    # Créer l'utilisateur admin par défaut s'il n'existe pas
    try:
        admin = Utilisateur.query.filter_by(username='admin').first()
        if not admin:
            admin = Utilisateur(
                username='admin',
                nom='Administrateur',
                email='m.boyer3215@gmail.com',
                role='admin'
            )
            admin.set_password('MiB2025!')
            db.session_presta.add(admin)
            db.session_presta.commit()
            print("✅ Utilisateur admin créé")
    except Exception as e:
        print(f"Note: {e}")

with app.app_context():
    db.create_all()
    try:
        admin = Utilisateur.query.filter_by(username='admin').first()
        if not admin:
            admin = Utilisateur(username='admin', nom='Administrateur', email='m.boyer3215@gmail.com', role='admin')
            admin.set_password('MiB2025!')
            db.session_presta.add(admin)
            db.session_presta.commit()
    except:
        pass
        

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)       






