from setuptools import setup, find_packages

setup(
    name="admin-bot",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "python-telegram-bot[job-queue]>=20.0",
        "pymongo==4.5.0",
        "dnspython==2.4.2",
        "python-dotenv==1.0.0",
    ],
)
