import argparse
import os
import pkg_resources
import re
import zipfile


def installedpktlist():
    """
    Установленнные пакеты в виде словаря
    :return: Словарь с версиями установленных пакетов
    """
    return {d.project_name.lower(): d.version for d in pkg_resources.working_set}


class Dep:
    def __init__(self, name, version=None, addition=None):
        self.name = name
        self.version = version
        self.addition = addition

    def geturl(self):
        return 'https://pypi.org/project/{}/#history'.format(self.name)

    def __str__(self):
        s = self.name
        if self.version:
            s += ' ' + self.version
        if self.addition:
            s += ' ' + self.addition
        return s


class Pkt:
    def __init__(self, filepath: str):
        self.filepath = filepath
        md = self.metadatafromwheel(filepath)
        self.name = md['Name']
        self.version = md['Version']
        self.deps = []
        for dep in md['Requires-Dist']:
            m = re.match(r'([^ !><=]+)(?: *([^;]+))?(?: *; *(.+))?', dep)
            g = m.groups()
            self.deps.append(Dep(name=g[0], version=g[1], addition=g[2]))

    @classmethod
    def metadatafromwheel(cls, filepath):
        with zipfile.ZipFile(filepath, 'r') as z:
            metadatapath = []
            for i in z.namelist():
                if re.match(r'[^/]+\.dist-info/METADATA', i):
                    metadatapath.append(i)
            if len(metadatapath) != 1:
                raise ValueError('Incorrect file')
            md = cls.parsemetadata(z.read(metadatapath[0]))
        return md

    @staticmethod
    def parsemetadata(rawmetadata: bytes):
        rawmetadata = rawmetadata.decode('utf-8')
        lines = rawmetadata.split('\n')
        md = {
            'Requires-Dist': [],
        }
        for line in lines:
            pp = line.split(':', maxsplit=1)
            if len(pp) == 2:
                k, v = pp
                k = k.strip()
                v = v.strip()
                if k in md:
                    if isinstance(md[k], list):
                        md[k].append(v)
                    else:
                        md[k] = [md[k]]
                else:
                    md[k] = v
            else:
                break
        return md


def scandirforpkts(rootpath, exclude=tuple()):
    """
    Ищет пакеты в каталоге
    :param rootpath: Каталог, в котором нужно искать пакеты
    :param exclude: Список файлов, которые нужно исключить из выдачи
    :return: Список пакетов
    """
    exclude = tuple(os.path.normpath(i) for i in exclude)
    pkts = []
    for root, dirs, files in os.walk(rootpath):
        for filname in files:
            if os.path.normpath(filname) in exclude:
                continue
            if os.path.splitext(filname)[1] == '.whl':
                filepath = os.path.join(root, filname)
                pkt = Pkt(filepath)
                pkts.append(pkt)
        break
    return pkts


def checkdeps(startpktpath, dldir='', *, require_venv=True, ignore_installed=False):
    """
    Помощник скачивания пакетов для ручной установки. Формат пакетов: wheel
    :param startpktpath: Путь к пакету, который требуется установить
    :param dldir: Путь к каталогу с зависимостями. В него качать пакеты
    :param require_venv: Требовать virtualenv (см. параметр pip --require-virtualenv)
    :param ignore_installed: Игнорировать уже установленные пакеты
    """
    rootpkt = Pkt(startpktpath)
    pkts = scandirforpkts(dldir, exclude=(startpktpath,))
    if not ignore_installed:
        installed = installedpktlist()
    else:
        installed = {}
    deps = list(rootpkt.deps)
    remain = []
    needinstall = [rootpkt]
    for dep in deps:
        name = dep.name
        found = False
        for pktname in installed:
            if pktname.lower() == name.lower():
                found = True
                break
        if not found:
            for pkt in pkts:
                if pkt.name.lower() == name.lower():
                    found = True
                    needinstall.append(pkt)
                    for dep2 in pkt.deps:
                        if dep2.name.lower() not in (i.name.lower() for i in deps):
                            deps.append(dep2)
                    break
        if found:
            pass
            print('+', dep)
        else:
            remain.append(dep)
            print('-', dep)

    print('\nОсталось скачать:')
    for dep in remain:
        print(dep, dep.geturl())

    if len(remain) == 0:
        # Расчет порядка установки пакетов
        installed2 = [i.lower() for i in installed]
        need2 = list(needinstall)
        order = []
        while need2:
            for i, pkt in enumerate(need2):
                ok = True
                for dep in pkt.deps:
                    if dep.name.lower() not in installed2:
                        ok = False
                        break
                if ok:
                    order.append(pkt)
                    installed2.append(pkt.name.lower())
                    del need2[i]
                    break
            else:
                raise RuntimeError('Не получается рассчитать порядок установки')
        print('\nПорядок установки:')
        for pkt in order:
            print(pkt.filepath)

        installbatpath = 'install_{}.bat'.format(rootpkt.name)
        with open(installbatpath, 'w', encoding='ascii') as fp:
            print('@echo on', file=fp)
            print('', file=fp)
            pipopts = [
                '--disable-pip-version-check',
            ]
            if require_venv:
                pipopts.append('--require-virtualenv')
            for pkt in order:
                print('pip install', *pipopts, pkt.filepath, file=fp)
        print('\nФайл {} сохранен!'.format(installbatpath))

        print('Готово!')


def main():
    parser = argparse.ArgumentParser(
        description='Помощник скачивания пакетов при автономной установке.\n'
                    'Поддерживаются только пакеты в формате wheel.\n'
                    'Запускать программу и качать указанные пакеты, пока все пакеты не будут скачены.'
    )
    parser.add_argument('--no-venv', dest='no_venv', action='store_true', default=False,
                        help='Не требовать virtualenv')
    parser.add_argument('--no-installed', dest='no_installed', action='store_true', default=False,
                        help='Не учитывать уже установленные пакеты')
    parser.add_argument('--dldir', type=str, default='.', help='Каталог с пакетами')
    parser.add_argument('PACKET', help='Начальный пакет для установки')
    args = parser.parse_args()
    require_venv = not args.no_venv
    ignore_installed = args.no_installed
    checkdeps(args.PACKET, dldir=args.dldir, require_venv=require_venv, ignore_installed=ignore_installed)


if __name__ == '__main__':
    main()
