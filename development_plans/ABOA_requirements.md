# ABOA requirements

ABOA stands for Archive for Business Operations Analysis.

The following represents the requirements to be covered by ABOA

1. ABOA shall receive requests to:  
   1. Archive files  
   2. Retrieve files  
   3. Delete files  
2. ABOA shall be composed of a file system archive and a database inventory  
3. The file system archive will be based on POSIX  
4. The database inventory will be based on Postgres  
5. The design of the data model will be done in pgmodeler  
6. The database inventory shall include the following metadata:  
   1. name  
   2. path  
   3. reception date  
   4. archive date  
   5. file size  
   6. last access date (optional)  
   7. file type (optional)  
   8. file class (optional)  
   9. file version (optional)  
   10. validity date (optional)  
   11. generation date (optional)  
   12. removal date (optional)  
7. ABOA shall provide the following APIs:  
   1. Command line API  
   2. RESTFul API  
8. Retrieval requests shall allow filters on the associated metadata  
9. Retrieval requests shall allow the following selection rules  
   1. order by the corresponding metadata  
   2. group by the corresponding metadata  
   3. first  
   4. last  
   5. all  
10. Retrieval requests shall allow pagination  
11. ABOA shall log operations with different log levels  
12. ABOA shall provide an API to configure the management of files through an XML with the following structure:  
    1. \<archive\_configurations root\_directory=””\>  
    2. \<archive\_configuration\>  
    3. \<file\_mask\>\</file\_mask\>  
    4. \<file\_directory\>\</file\_directory\>  
    5. \<file\_processor\>\</file\_processor\>  
    6. \</archive\_configuration\>  
    7. \</archive\_configurations\>  
13. ABOA shall archive files in a structured directory: file\_directory/YEAR/MONTH/DAY  
14. ABOA shall evaluate the structure of the configuration using an XSD schema  
15. ABOA shall archive a file even if the file is not matching any configuration in “unknown” folder  
16. ABOA shall not accept any configuration which defines file\_directory with the value “unknown”  
17. ABOA shall allow the execution of the file processors to extract the relevant metadata of files declared in the configuration  
18. ABOA shall keep history of all configured root directories  
19. ABOA shall allow the configuration of retention policies based on:  
    1. File-types  
    2. Last access date  
    3. validity time  
    4. Reception date  
    5. Generation date  
    6. Archive date  
    7. Removal date  
20. ABOA shall have tests covering all the code of the component