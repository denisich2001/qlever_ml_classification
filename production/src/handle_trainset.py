import pandas as pd
from loguru import logger

from nltk.corpus import stopwords
from sklearn.decomposition import PCA
from sklearn.preprocessing import LabelEncoder
from imblearn.over_sampling import RandomOverSampler
from sklearn.feature_extraction.text import TfidfVectorizer

from production.config import TargetColumnName
from production.config import PCAComponentsNumber
from production.src.utils.errors import EmptyValuesAfterEncoding
from production.src.utils.features_preprocessing import text_feature_preprocessing

russian_stopwords = stopwords.words("russian")


class DataHandler:
    """
    Класс обработки данных для работы с моделью.
    Состоит из двух независимых основных методов:
    1. Подготовки данных для тренировки модели:
        * Кодирование строковых и категориальных факторов (fit и transform TfidfVectorizer)
        * Устранение несбалансированности классов
        * Снижение размерности с помощью PCA (fit и transform)
    2. Подготовки данных для тестирования модели - все те же методы (кроме устранения несбалансированности),
        только используются уже обученные TfidfVectorizer и PCA
    """

    def __init__(
            self, input_table_types_dict
    ) -> None:
        self.input_table_types_dict = input_table_types_dict
        # Вид текущего датасета (train/test)
        self.dataset_type = None
        # Сохраняем pca и vectorizer, чтобы обучить их на train выборке, а потом использовать на test
        self.vectorizer = None
        self.pca = None
        # Переменные для итогового трейнсета после всех обработок
        self.final_dataset_features = None
        self.final_dataset_target = None

    def prepare_traindata(self, original_dataset, print_logs: bool = False):
        """
        Метод подготовки данных для тренировки.

        Returns
        -------
        trainset_features и trainset_target - факторы и таргет сформированного трейнсета
        """
        if print_logs:
            logger.info('Начинаем подготовку тренировочных данных.')
        self.dataset_type = 'train'
        primary_dataset = original_dataset.copy()
        balanced_dataset = DataHandler.trainset_target_balancing(primary_dataset, print_logs)
        self.final_dataset_target = balanced_dataset[TargetColumnName]
        no_target_dataset = balanced_dataset.drop(TargetColumnName, axis=1)
        encoded_dataset = self.encode_features(no_target_dataset, print_logs)
        self.final_dataset_features = self.pca_transformation(
            encoded_dataset,
            print_logs
        )
        if print_logs:
            logger.info('Тренировочные данные успешно подготовлены.')
        return self.final_dataset_features, self.final_dataset_target

    def prepare_prediction_or_test_data(self, original_dataset, print_logs: bool = False):
        """
        Метод подготовки данных для теста или предсказания.

        Returns
        -------
        trainset_features и trainset_target - факторы и таргет сформированного трейнсета
        """
        if print_logs:
            logger.info('Начинаем подготовку данных для предсказания.')
        self.dataset_type = 'test'
        primary_dataset = original_dataset.copy()
        self.final_dataset_target = primary_dataset[TargetColumnName]
        no_target_dataset = primary_dataset.drop(TargetColumnName, axis=1)
        encoded_dataset = self.encode_features(no_target_dataset, print_logs)
        logger.debug(f'Размеры тестового {encoded_dataset.shape} и {self.final_dataset_target.size}')
        self.final_dataset_features = self.pca_transformation(
            encoded_dataset,
            print_logs
        )
        if print_logs:
            logger.info('Данные успешно подготовлены.')
        return self.final_dataset_features, self.final_dataset_target

    @staticmethod
    def trainset_target_balancing(original_dataset: pd.DataFrame, print_logs: bool = False):
        """
        Метод устранения несбалансированности классов. Используем пересемплирование.
        Parameters
        ----------
        original_dataset - основной трейнсет
        """
        if print_logs:
            logger.info('Устраним несбалансированность классов.')
        trainset = original_dataset.copy()
        if print_logs:
            logger.debug(f'2 самых частых и самых редких класса до балансировки:\n'
                         f'{trainset.value_counts()[:2]}\n{trainset.value_counts()[-2:]}')
        ros = RandomOverSampler()
        balanced_features, balanced_target = ros.fit_resample(
            trainset.drop(TargetColumnName, axis=1),
            trainset[TargetColumnName]
        )
        balanced_trainset = pd.concat([balanced_features, balanced_target], axis=1)
        if print_logs:
            logger.info('Устранили несбалансированность классов.')
        return balanced_trainset

    def pca_transformation(
            self,
            original_dataset: pd.DataFrame,
            print_logs: bool = False
    ):
        """
        Метод снижения размерности трейнсета методом главных компонент.

        Parameters
        ----------
        original_dataset - основной трейнсет
        original_products_for_classification - данные для предсказания
        """
        trainset = original_dataset.copy()
        if print_logs:
            logger.info('Снизим размерность используя метод главных компонент.')
            logger.debug(f'Размерность до: {trainset.shape}')
        #if self.dataset_type == 'train':
        #    self.pca = PCA(n_components=PCAComponentsNumber)
        #    self.pca.fit(trainset)
        self.pca = PCA(n_components=PCAComponentsNumber)
        self.pca.fit(trainset)
        reduced_trainset = pd.DataFrame(self.pca.transform(trainset))
        if print_logs:
            logger.debug(f'Размерность после: {reduced_trainset.shape}')
            logger.debug(f'PCA explained variance ratio:\n {self.pca.explained_variance_ratio_}')
        return reduced_trainset

    def encode_features(
            self,
            original_dataset: pd.DataFrame,
            print_logs: bool = False
    ):
        """
        Метод кодирования строковых и категориальных факторов модели
        """
        if print_logs:
            logger.info('Начинаем кодирование факторов.')
        product_table = original_dataset.copy()
        logger.debug(f'Размеры product_table {product_table.shape}')
        logger.debug(f'input_table_types_dict: {self.input_table_types_dict}')
        product_table_encoded = pd.DataFrame()
        for feature in self.input_table_types_dict:
            if self.input_table_types_dict.get(feature) == 'Стр':
                handled_feature = self.handle_text_feature(product_table[feature])
            elif self.input_table_types_dict.get(feature) == 'Кат':
                handled_feature = self.handle_cat_feature(product_table[feature])
                logger.debug(f'feature:{feature}. handled_feature: {handled_feature.shape}')
            else:
                handled_feature = pd.DataFrame(product_table[feature])
            #handled_feature.columns = [str(col) + '_' + str(feature) for col in handled_feature.columns]
            product_table_encoded = pd.concat([product_table_encoded, handled_feature], axis=1)
            logger.debug(f'Feature: {feature}. Размеры: {product_table_encoded.shape}')

        #TODO УБРАТЬ СЛЕДУЮЩУЮ СТРОЧКУ И ОТЛАДИТЬ БЕЗ НЕЕ
        product_table_encoded = product_table_encoded.fillna(0)
        # Т.к. мы пересобирали датасет заново во время кодирования => перепроверим на наличие пропущеных значений
        if product_table_encoded.isna().sum().sum() > 0:
            if print_logs:
                logger.error('Появились пустые значения после кодирования переменных')
            raise EmptyValuesAfterEncoding('Появились пустые значения после кодирования переменных!')
        if print_logs:
            logger.info(f'Получилось {product_table_encoded.columns.size} факторов после кодирования')
        return product_table_encoded

    def handle_cat_feature(self, cat_feature: pd.Series):
        """
        Метод кодирования категориального фактора - используем OneHotEncoding
        """
        #logger.debug(f'cat_feature before: {cat_feature.size}')
        cat_feature = cat_feature.astype(str)
        cat_feature_encoded = pd.get_dummies(cat_feature)
        #logger.debug(f'cat_feature after: {cat_feature_encoded.size}')
        #logger.debug(f'cat_feature: {pd.concat([cat_feature,cat_feature_encoded], axis = 1)}')
        return cat_feature_encoded

    def handle_text_feature(self, text_feature: pd.Series):
        """
        Метод обработки и кодирования строкового фактора:
        - Проводим препроцессинг
        - Используем TFidfVectorizer
        """
        processed_text_feature = text_feature_preprocessing(text_feature)
        # Если dataset_type == 'train' => мы кодируем тренировочные данные,
        # Иначе - тестовые данные, для них нужно использовать уже обученный
        if self.dataset_type == 'train':
            self.vectorizer = TfidfVectorizer(
                max_features=100,
                analyzer='word',
                stop_words=russian_stopwords
            )
            self.vectorizer.fit(processed_text_feature)
        vectorized_text_feature = pd.DataFrame(self.vectorizer.transform(processed_text_feature).toarray())
        vectorized_text_feature.columns = pd.Series(self.vectorizer.get_feature_names_out())
        return vectorized_text_feature
