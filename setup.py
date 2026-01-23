from setuptools import setup, find_packages

setup(
    name='pass_nice',
    version='2.1.1',
    description='NICE 아이디 본인인증 요청을 자동화해주는 비공식 모듈',
    author='shy9-29',
    author_email='sunr1s2@proton.me',
    url='https://github.com/shy9-29/PASS-NICE',
    install_requires=['httpx>=0.25.0'],
    packages=find_packages(exclude=[]),
    keywords=['nice', 'verification', 'sms', 'identity', 'korea', 'authentication'],
    python_requires='>=3.8',
    package_data={},
    zip_safe=False,
    classifiers=[
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
    ],
)
