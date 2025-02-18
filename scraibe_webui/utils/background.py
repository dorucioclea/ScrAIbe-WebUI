import re
from unicodedata import normalize

from os import remove
from os.path import join, split

from threading import Thread, BoundedSemaphore, active_count
from scraibe.misc import set_threads

from scraibe_webui.global_var import MAX_CONCURRENT_MODELS
import scraibe_webui.global_var as gv
from .mail import MailService
from .wrapper import ScraibeWrapper

threadLimiter = BoundedSemaphore(MAX_CONCURRENT_MODELS)

class BoundedThread(Thread):
    """
    Custom Thread class that limits the number of threads that can run concurrently
    """
    def run(self):
        threadLimiter.acquire() # Get Global Thread Limiter
        try:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)
        finally:
            threadLimiter.release()
            del self._target, self._args, self._kwargs


class BackgroundThread:
    """
    Handle background process for transcribing audio and sending the result to the client using Email
    """
    def __init__(self, mail_service_params : dict,
                        scraibe_kwargs : dict,
                        threads_per_model : int = 4, 
                        
                        
                        ) -> None:
        """
        Background Thread for transcribing audio and sending the result to the client using Email. This class contains all the necessary methods to run the background process.
        
        Args:
            mail_service_params (dict): The mail service parameters.
            scraibe_kwargs (dict): The model parameters.
            threads_per_model (int, optional): The number of threads per model. Defaults to 4.  If set to 0 the number of threads will be set to the number of cores available.
        
        """
        self.mail_service_params = mail_service_params
        self.scraibe_kwargs = scraibe_kwargs
        self.threads_per_model = threads_per_model
        
    def parrallel_task(self,
                       audio : str,
                       reciever : str,
                       task : str,
                       num_speakers : int,
                       translate : bool,
                       language : str,
                       error_format_options : dict = {},
                       success_format_option : dict = {}
                       ) -> None:
        
        """ Background task that runs in a separate thread """
        
        if self.threads_per_model  is not None:
            set_threads(yaml_threads = self.threads_per_model) 
        
        # List to store temporary files
        temp_files = []
        
        try:
            # setup Scraibe if not already setup
           
            _scraibe = ScraibeWrapper.load_from_dict(self.scraibe_kwargs)
            
            if isinstance(audio, str):
                
                _out_base_filename = normalize_filename(audio.split('.')[0])
                
                temp_file_path_txt = join(f'{_out_base_filename}.txt')
                temp_file_path_json = join(f'{_out_base_filename}.json')
                
                
                if task == 'Auto Transcribe':

                    _ , result_txt, result_json = _scraibe.autotranscribe(audio,
                                                        num_speakers = num_speakers,
                                                        translate = translate,
                                                        language = language)

                    with open(temp_file_path_txt, 'w') as temp_file:
                        temp_file.write(str(result_txt))
                    
                    with open(temp_file_path_json, 'w', encoding='utf-8') as temp_file:
                           temp_file.write(str(result_json))
                    
                    temp_files.append(temp_file_path_txt)
                    temp_files.append(temp_file_path_json)                   
                
                elif task == 'Transcribe':
                    result = _scraibe.transcribe(audio,
                                                    translate = translate,
                                                    language = language)

                    with open(temp_file_path_txt, 'w') as temp_file:
                        temp_file.write(str(result))
                    
                    temp_files.append(temp_file_path_txt)
                
                elif task == 'Diarisation':
                    result = _scraibe.diarisation(audio, num_speakers = num_speakers)
                    
                    with open(temp_file_path_json, 'w') as temp_file:
                        temp_file.write(result)
                    
                    temp_files.append(temp_file_path_json)
                
            elif isinstance(audio, list):
                
                for aud in audio:
                    
                    temp_file_path_txt = join(aud.split('.')[0] + '.txt')
                    temp_file_path_json = join(aud.split('.')[0] + '.json')
                    
                    
                    if task == 'Auto Transcribe':
                        _ , result_txt, result_json = _scraibe.autotranscribe(aud,
                                                        num_speakers = num_speakers,
                                                        translate = translate,
                                                        language = language)
                       
                        with open(temp_file_path_txt, 'w') as temp_file:
                            temp_file.write(str(result_txt))
                    
                        with open(temp_file_path_json, 'w', encoding='utf-8') as temp_file:
                            temp_file.write(str(result_json))
                        
                        temp_files.append(temp_file_path_txt)
                        temp_files.append(temp_file_path_json)                   
                
                    elif task == 'Transcribe':
                        result = _scraibe.transcribe(aud,
                                                    translate = translate,
                                                    language = language)

                        with open(temp_file_path_txt, 'w') as temp_file:
                            temp_file.write(str(result))
                    
                        temp_files.append(temp_file_path_txt)
                        
                    elif task == 'Diarisation':
                        result = _scraibe.diarisation(aud, num_speakers = num_speakers)
                        
                        with open(temp_file_path_json, 'w') as temp_file:
                            temp_file.write(result)
                    
                        temp_files.append(temp_file_path_json)

            MailService.from_config(self.mail_service_params).send_transcript(receiver_email=reciever, transcript_paths = temp_files, **success_format_option)
        
        except Exception as exeption:
            
            MailService.from_config(self.mail_service_params).send_error_notification(receiver_email = reciever, exception_message = exeption, **error_format_options)
        
        for file in temp_files:
            remove(file)
        
        gv.NUMBER_OF_QUEUE -= 1
        del _scraibe # Delete Scraibe object after use
        
    def run(self,
            audio : str,
            reciever : str,
            task : str,
            num_speakers : int,
            translate : bool,
            language : str,
            error_format_options : dict = {},
            transcript_format_options : dict = {}, *args, **kwargs):
        """ Run the background process """
        _thread = BoundedThread(target=self.parrallel_task,
                                args=(audio,
                                      reciever,
                                      task,
                                    num_speakers,
                                    translate,
                                    language,
                                    error_format_options,
                                    transcript_format_options, *args),
                                kwargs=kwargs).start()
        return _thread
    
    @property
    def get_active_threads(self):
        """ Get the number of active threads """
        return active_count()
    



def normalize_filename(path):
    """
    Sanitizes a filename within a Gradio-based automated transcription framework before 
    sending the file via SMTP. This utility function ensures filenames conform to SMTP-safe 
    standards by removing or replacing special characters and spaces that may cause issues 
    during email transmission.

    Background:
        Filenames may contain special characters or spaces (e.g., accented letters, non-ASCII symbols) which can lead to 
        problems with email clients or servers. This function is used to standardize 
        filenames before sending them through SMTP.

    Args:
        path (str): The original filename of the media file generated during transcription, 
                        which may contain special characters, spaces, or accents.

    Returns:
        str: A sanitized filename that is safe to use with SMTP and email clients, ensuring 
             proper file transmission.

    Example:
        >>> normalize_filename("/path/to/Reunión 24 de agosto.mp4")
        '/path/to/Reunion_24_de_agosto.mp4'
    """
    
    # Split the path into directory and file components
    directory, filename = split(path)
    # Normalize Unicode characters to their closest ASCII equivalent
    nfkd_form = normalize('NFKD', filename)
    ascii_filename = nfkd_form.encode('ASCII', 'ignore').decode('ASCII')
    
    # Replace spaces with underscores
    ascii_filename = ascii_filename.replace(" ", "_")
    
    # Remove any characters that aren't alphanumeric, underscores, hyphens, or dots
    ascii_filename = re.sub(r'[^a-zA-Z0-9._-]', '', ascii_filename)
    
    # Rejoin the directory and the sanitized filename
    return join(directory, ascii_filename)
